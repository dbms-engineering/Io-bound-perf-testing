//! The three parallelization strategies from the paper (Sec. II). Workers do not
//! communicate; each one processes its own contiguous slice of the shuffled URL list.

use std::collections::HashMap;
use std::io::{self, Read, Write};
use std::time::Duration;

use mio::net::TcpStream;
use mio::{Events, Interest, Poll, Token};

use crate::common::{split_ranges, CrawlStats, Target, MAX_ATTEMPTS};
use crate::http::{account, build_request, BlockingClient, ResponseParser};

/// The "abstract crawler" from the paper. Common operations are implemented in
/// `common` and `http`; each implementation only defines how the URL queue is
/// processed.
pub trait Crawler {
    fn name(&self) -> String;
    fn run(&self, urls: &[String]) -> CrawlStats;
}

/// Crawls one slice sequentially with blocking I/O. Used by both the process
/// pool and the thread pool.
fn crawl_slice(target: &Target, urls: &[String]) -> CrawlStats {
    let mut stats = CrawlStats::default();
    let mut freq = HashMap::new();
    let mut client = BlockingClient::new(target.clone());
    for u in urls {
        client.fetch(u, &mut stats, &mut freq);
    }
    stats
}

pub struct ProcessPool {
    pub target: Target,
    pub workers: usize,
}

impl Crawler for ProcessPool {
    fn name(&self) -> String {
        "process".into()
    }

    fn run(&self, urls: &[String]) -> CrawlStats {
        let ranges = split_ranges(urls.len(), self.workers);
        let mut children = Vec::with_capacity(ranges.len());
        for &(b, e) in &ranges {
            let mut fds = [0i32; 2];
            // SAFETY: These are plain POSIX calls. The parent process is
            // single-threaded when it forks, so the child can safely continue
            // executing Rust code.
            unsafe {
                assert_eq!(libc::pipe(fds.as_mut_ptr()), 0, "pipe() failed");
                let pid = libc::fork();
                assert!(pid >= 0, "fork() failed");
                if pid == 0 {
                    libc::close(fds[0]);
                    let s = crawl_slice(&self.target, &urls[b..e]);
                    let p = &s as *const CrawlStats as *const libc::c_void;
                    libc::write(fds[1], p, std::mem::size_of::<CrawlStats>());
                    libc::close(fds[1]);
                    libc::_exit(0); // Skip destructors and atexit handlers inherited from the parent.
                }
                libc::close(fds[1]);
                children.push((pid, fds[0], e - b));
            }
        }
        let mut total = CrawlStats::default();
        for (pid, rfd, len) in children {
            let mut s = CrawlStats::default();
            let size = std::mem::size_of::<CrawlStats>();
            let mut got = 0usize;
            // SAFETY: A repr(C) struct of u64 fields accepts any bit pattern.
            unsafe {
                let dst = &mut s as *mut CrawlStats as *mut u8;
                while got < size {
                    let r = libc::read(rfd, dst.add(got) as *mut libc::c_void, size - got);
                    if r <= 0 {
                        break;
                    }
                    got += r as usize;
                }
                libc::close(rfd);
                let mut status = 0;
                libc::waitpid(pid, &mut status, 0);
            }
            if got == size {
                total.add(&s);
            } else {
                total.errors += len as u64; // The child failed; count its whole slice as errors.
            }
        }
        total
    }
}

pub struct ThreadPool {
    pub target: Target,
    pub workers: usize,
}

impl Crawler for ThreadPool {
    fn name(&self) -> String {
        "thread".into()
    }

    fn run(&self, urls: &[String]) -> CrawlStats {
        let ranges = split_ranges(urls.len(), self.workers);
        std::thread::scope(|scope| {
            let handles: Vec<_> = ranges
                .iter()
                .map(|&(b, e)| scope.spawn(move || crawl_slice(&self.target, &urls[b..e])))
                .collect();
            let mut total = CrawlStats::default();
            for h in handles {
                total.add(&h.join().expect("worker thread panicked"));
            }
            total
        })
    }
}

pub struct EventLoop {
    pub target: Target,
    pub threads: usize,
    pub conns: usize,
}

impl EventLoop {
    pub fn backend() -> &'static str {
        if cfg!(any(target_os = "linux", target_os = "android")) {
            "epoll"
        } else {
            "kqueue"
        }
    }
}

impl Crawler for EventLoop {
    fn name(&self) -> String {
        format!("event-{}", Self::backend())
    }

    fn run(&self, urls: &[String]) -> CrawlStats {
        let ranges = split_ranges(urls.len(), self.threads);
        std::thread::scope(|scope| {
            let handles: Vec<_> = ranges
                .iter()
                .map(|&(b, e)| {
                    scope.spawn(move || {
                        Loop::new(&self.target, &urls[b..e], self.conns)
                            .expect("cannot create poller")
                            .run()
                    })
                })
                .collect();
            let mut total = CrawlStats::default();
            for h in handles {
                total.add(&h.join().expect("event loop thread panicked"));
            }
            total
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum State {
    Idle,
    Broken,     // connect() failed immediately.
    Connecting, // Waiting for the non-blocking connect to complete.
    Sending,
    Receiving,
}

struct Conn {
    stream: Option<TcpStream>,
    state: State,
    out: Vec<u8>,
    off: usize,
    parser: ResponseParser,
    url: usize,
    attempts: u32,
}

enum Step {
    Continue,
    Wait,
}

/// A single M:N worker: a readiness loop over `conns` non-blocking keep-alive
/// connections. Because mio is edge-triggered, each handler makes as much
/// progress as possible until the socket returns `WouldBlock`.
///
/// ```text
///  Connecting --writable--> Sending --request sent--> Receiving
///                              ^                          |
///                              +---- next URL (keep-alive)+
///  on error or EOF -> reconnect and retry (up to MAX_ATTEMPTS)
/// ```
struct Loop<'a> {
    poll: Poll,
    target: &'a Target,
    urls: &'a [String],
    next: usize,
    conns: Vec<Conn>,
    active: usize,
    stats: CrawlStats,
    freq: HashMap<String, u32>,
    buf: Vec<u8>,
}

impl<'a> Loop<'a> {
    fn new(target: &'a Target, urls: &'a [String], conns: usize) -> io::Result<Self> {
        Ok(Loop {
            poll: Poll::new()?,
            target,
            urls,
            next: 0,
            conns: (0..conns.max(1))
                .map(|_| Conn {
                    stream: None,
                    state: State::Idle,
                    out: Vec::new(),
                    off: 0,
                    parser: ResponseParser::default(),
                    url: 0,
                    attempts: 0,
                })
                .collect(),
            active: 0,
            stats: CrawlStats::default(),
            freq: HashMap::new(),
            buf: vec![0; 64 * 1024],
        })
    }

    fn run(mut self) -> CrawlStats {
        for i in 0..self.conns.len() {
            if self.assign_next(i) {
                self.drive(i);
            }
        }
        let mut events = Events::with_capacity(256);
        while self.active > 0 {
            if let Err(e) = self.poll.poll(&mut events, Some(Duration::from_secs(1))) {
                if e.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                panic!("poll failed: {e}");
            }
            for ev in events.iter() {
                self.drive(ev.token().0);
            }
        }
        self.stats
    }

    /// Assigns the next URL to connection `i`, or closes the connection when the
    /// slice is exhausted. Returns `false` if no URL remains.
    fn assign_next(&mut self, i: usize) -> bool {
        if self.next >= self.urls.len() {
            self.close(i);
            return false;
        }
        let c = &mut self.conns[i];
        c.url = self.next;
        c.attempts = 0;
        self.next += 1;
        self.prepare(i);
        true
    }

    fn prepare(&mut self, i: usize) {
        let c = &mut self.conns[i];
        c.out = build_request(&self.target.host, &self.urls[c.url]);
        c.off = 0;
        c.attempts += 1;
        if c.stream.is_some() {
            c.state = State::Sending; // Reuse the existing keep-alive connection.
            return;
        }
        match TcpStream::connect(self.target.addr) {
            Ok(mut s) => {
                let _ = s.set_nodelay(true);
                if self
                    .poll
                    .registry()
                    .register(&mut s, Token(i), Interest::READABLE | Interest::WRITABLE)
                    .is_err()
                {
                    c.state = State::Broken;
                    return;
                }
                c.stream = Some(s);
                c.state = State::Connecting;
                self.active += 1;
            }
            Err(_) => c.state = State::Broken,
        }
    }

    fn close(&mut self, i: usize) {
        let c = &mut self.conns[i];
        if let Some(mut s) = c.stream.take() {
            let _ = self.poll.registry().deregister(&mut s);
            self.active -= 1;
        }
        c.parser.reset();
        c.state = State::Idle;
    }

    /// Advances connection `i` until it must wait for the operating system.
    fn drive(&mut self, i: usize) {
        loop {
            let step = match self.conns[i].state {
                State::Idle => Step::Wait,
                State::Broken => self.fail(i),
                State::Connecting => self.on_connecting(i),
                State::Sending => self.on_sending(i),
                State::Receiving => self.on_receiving(i),
            };
            if let Step::Wait = step {
                return;
            }
        }
    }

    fn on_connecting(&mut self, i: usize) -> Step {
        let s = self.conns[i].stream.as_ref().expect("connecting without a stream");
        match s.take_error() {
            Ok(Some(_)) | Err(_) => return self.fail(i),
            Ok(None) => {}
        }
        match s.peer_addr() {
            Ok(_) => {
                self.conns[i].state = State::Sending;
                Step::Continue
            }
            Err(e) if e.kind() == io::ErrorKind::NotConnected => Step::Wait,
            Err(_) => self.fail(i),
        }
    }

    fn on_sending(&mut self, i: usize) -> Step {
        let c = &mut self.conns[i];
        let s = c.stream.as_mut().expect("sending without a stream");
        while c.off < c.out.len() {
            match s.write(&c.out[c.off..]) {
                Ok(0) => return self.fail(i),
                Ok(n) => c.off += n,
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => return Step::Wait,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => {}
                Err(_) => return self.fail(i),
            }
        }
        c.state = State::Receiving;
        Step::Continue
    }

    fn on_receiving(&mut self, i: usize) -> Step {
        loop {
            let c = &mut self.conns[i];
            if c.parser.complete() {
                return self.finish(i);
            }
            let s = c.stream.as_mut().expect("receiving without a stream");
            match s.read(&mut self.buf) {
                Ok(0) => return self.fail(i), // EOF received before the response was complete.
                Ok(n) => {
                    c.parser.feed(&self.buf[..n]);
                    if c.parser.failed() {
                        return self.fail(i);
                    }
                }
                Err(e) if e.kind() == io::ErrorKind::WouldBlock => return Step::Wait,
                Err(e) if e.kind() == io::ErrorKind::Interrupted => {}
                Err(_) => return self.fail(i),
            }
        }
    }

    fn finish(&mut self, i: usize) -> Step {
        let c = &mut self.conns[i];
        account(&c.parser, &mut self.stats, &mut self.freq);
        let close = c.parser.server_closes();
        c.parser.reset();
        if close {
            self.close(i);
        }
        if self.assign_next(i) {
            Step::Continue
        } else {
            Step::Wait
        }
    }

    fn fail(&mut self, i: usize) -> Step {
        self.close(i);
        if self.conns[i].attempts < MAX_ATTEMPTS {
            self.prepare(i);
            Step::Continue
        } else {
            self.stats.errors += 1;
            if self.assign_next(i) {
                Step::Continue
            } else {
                Step::Wait
            }
        }
    }
}
