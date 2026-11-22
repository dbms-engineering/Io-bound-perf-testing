//! Minimal HTTP/1.1 client components: a request builder, an incremental
//! response parser (Content-Length framing only, which NGINX and the bundled
//! server use for static files), and a blocking keep-alive client.

use std::collections::HashMap;
use std::io::{self, Read, Write};
use std::net::TcpStream;

use crate::common::{collect_tags, CrawlStats, Target, MAX_ATTEMPTS};

pub fn build_request(host: &str, path: &str) -> Vec<u8> {
    format!(
        "GET {path} HTTP/1.1\r\nHost: {host}\r\nUser-Agent: io-bound-perf-crawler\r\n\
         Accept-Encoding: identity\r\nConnection: keep-alive\r\n\r\n"
    )
    .into_bytes()
}

#[derive(Debug, Default)]
pub struct ResponseParser {
    buf: Vec<u8>,
    header_end: Option<usize>,
    content_length: usize,
    status: u16,
    close: bool,
    complete: bool,
    failed: bool,
}

fn find(hay: &[u8], needle: &[u8]) -> Option<usize> {
    hay.windows(needle.len()).position(|w| w == needle)
}

impl ResponseParser {
    /// Appends received bytes. Returns `true` once a complete response has been buffered.
    pub fn feed(&mut self, data: &[u8]) -> bool {
        self.buf.extend_from_slice(data);
        self.try_parse()
    }
    pub fn complete(&self) -> bool {
        self.complete
    }
    pub fn failed(&self) -> bool {
        self.failed
    }
    pub fn status(&self) -> u16 {
        self.status
    }
    /// Returns `true` if the server sent `Connection: close`.
    pub fn server_closes(&self) -> bool {
        self.close
    }
    pub fn body(&self) -> &[u8] {
        match (self.complete, self.header_end) {
            (true, Some(h)) => &self.buf[h..h + self.content_length],
            _ => &[],
        }
    }

    /// Discards the current response while retaining any bytes that follow it.
    pub fn reset(&mut self) {
        match (self.complete, self.header_end) {
            (true, Some(h)) => {
                self.buf.drain(..h + self.content_length);
            }
            _ => self.buf.clear(),
        }
        let buf = std::mem::take(&mut self.buf);
        *self = ResponseParser { buf, ..Default::default() };
        if !self.buf.is_empty() {
            self.try_parse();
        }
    }

    fn try_parse(&mut self) -> bool {
        if self.complete || self.failed {
            return self.complete;
        }
        if self.header_end.is_none() {
            let Some(pos) = find(&self.buf, b"\r\n\r\n") else { return false };
            let head = String::from_utf8_lossy(&self.buf[..pos]).into_owned();
            let mut lines = head.split("\r\n");
            let status_line = lines.next().unwrap_or("");
            let status = status_line
                .strip_prefix("HTTP/1.")
                .and_then(|s| s.get(2..5))
                .and_then(|s| s.parse::<u16>().ok());
            let Some(status) = status else {
                self.failed = true;
                return false;
            };
            let mut length = None;
            for line in lines {
                let Some((k, v)) = line.split_once(':') else { continue };
                let (k, v) = (k.trim().to_ascii_lowercase(), v.trim().to_ascii_lowercase());
                if k == "content-length" {
                    length = v.parse::<usize>().ok();
                } else if k == "connection" {
                    self.close = v.contains("close");
                }
            }
            let Some(length) = length else {
                self.failed = true; // Chunked and unframed responses are not supported.
                return false;
            };
            self.status = status;
            self.content_length = length;
            self.header_end = Some(pos + 4);
        }
        let h = self.header_end.unwrap_or(0);
        self.complete = self.buf.len() >= h + self.content_length;
        self.complete
    }
}

/// Records a complete response in `stats` and runs the simulated parser on its body.
pub fn account(parser: &ResponseParser, stats: &mut CrawlStats, freq: &mut HashMap<String, u32>) {
    if parser.status() == 200 {
        let body = parser.body();
        stats.pages += 1;
        stats.bytes += body.len() as u64;
        stats.tags += collect_tags(body, freq);
    } else {
        stats.errors += 1;
    }
}

/// Blocking keep-alive client used by the process-pool and thread-pool crawlers.
pub struct BlockingClient {
    target: Target,
    stream: Option<TcpStream>,
    parser: ResponseParser,
    buf: Vec<u8>,
}

impl BlockingClient {
    pub fn new(target: Target) -> Self {
        BlockingClient { target, stream: None, parser: ResponseParser::default(), buf: vec![0; 64 * 1024] }
    }

    /// Downloads `path`, retrying on a new connection if necessary.
    pub fn fetch(&mut self, path: &str, stats: &mut CrawlStats, freq: &mut HashMap<String, u32>) {
        for _ in 0..MAX_ATTEMPTS {
            if self.try_once(path, stats, freq).is_ok() {
                return;
            }
            self.close();
        }
        stats.errors += 1;
    }

    fn close(&mut self) {
        self.stream = None;
        self.parser.reset();
    }

    fn try_once(&mut self, path: &str, stats: &mut CrawlStats, freq: &mut HashMap<String, u32>) -> io::Result<()> {
        if self.stream.is_none() {
            let s = TcpStream::connect(self.target.addr)?;
            s.set_nodelay(true)?;
            self.stream = Some(s);
        }
        let stream = self.stream.as_mut().expect("connected above");
        stream.write_all(&build_request(&self.target.host, path))?;
        while !self.parser.complete() {
            let n = stream.read(&mut self.buf)?;
            if n == 0 {
                return Err(io::ErrorKind::UnexpectedEof.into());
            }
            self.parser.feed(&self.buf[..n]);
            if self.parser.failed() {
                return Err(io::Error::new(io::ErrorKind::InvalidData, "bad HTTP response"));
            }
        }
        account(&self.parser, stats, freq);
        let close = self.parser.server_closes();
        self.parser.reset();
        if close {
            self.stream = None;
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_split_and_pipelined_responses() {
        let r1 = b"HTTP/1.1 200 OK\r\nContent-Length: 5\r\nConnection: keep-alive\r\n\r\nhello";
        let r2 = b"HTTP/1.1 404 Not Found\r\ncontent-length: 2\r\nConnection: close\r\n\r\nno";
        let mut p = ResponseParser::default();
        assert!(!p.feed(&r1[..20]));
        let mut rest = r1[20..].to_vec();
        rest.extend_from_slice(r2);
        assert!(p.feed(&rest));
        assert_eq!((p.status(), p.body(), p.server_closes()), (200, &b"hello"[..], false));
        p.reset();
        assert!(p.complete());
        assert_eq!((p.status(), p.body(), p.server_closes()), (404, &b"no"[..], true));
    }

    #[test]
    fn rejects_unframed_responses() {
        let mut p = ResponseParser::default();
        p.feed(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n");
        assert!(p.failed());
    }
}
