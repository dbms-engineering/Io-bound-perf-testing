//! static_server: a minimal keep-alive HTTP/1.1 server for static HTML files.
//!
//! Replaces the NGINX instance used in the paper. All dataset files are loaded
//! into memory at startup (the paper serves them from a RAM disk). The server
//! uses no TLS and no compression, and runs one thread per connection (the
//! crawlers open at most a few dozen connections).
//!
//! ```text
//! static_server --root data/pages [--bind 127.0.0.1] [--port 8080]
//!               [--delay-us 200] [--max-requests 0]
//! ```
//!
//! `--delay-us` adds a fixed service delay before each response to emulate
//! network and server latency, so that the workload remains I/O-bound even on
//! the loopback interface. `--max-requests N` closes a connection after N
//! responses, similar to the NGINX `keepalive_requests` directive; this
//! exercises the reconnection path of the crawlers.

use std::collections::HashMap;
use std::fs;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::path::Path;
use std::sync::Arc;
use std::thread;
use std::time::Duration;

struct Config {
    delay: Duration,
    max_requests: u64,
    files: HashMap<String, Vec<u8>>,
}

fn load_dir(dir: &Path, prefix: &str, out: &mut HashMap<String, Vec<u8>>) -> std::io::Result<()> {
    for entry in fs::read_dir(dir)? {
        let entry = entry?;
        let name = entry.file_name().to_string_lossy().into_owned();
        let url = format!("{prefix}/{name}");
        let ty = entry.file_type()?;
        if ty.is_dir() {
            load_dir(&entry.path(), &url, out)?;
        } else if ty.is_file() {
            out.insert(url, fs::read(entry.path())?);
        }
    }
    Ok(())
}

fn response(body: &[u8], status: u16, close: bool) -> Vec<u8> {
    let reason = if status == 200 { "OK" } else { "Not Found" };
    let conn = if close { "close" } else { "keep-alive" };
    let mut r = format!(
        "HTTP/1.1 {status} {reason}\r\nServer: io-bound-perf-static\r\nContent-Type: text/html\r\n\
         Content-Length: {}\r\nConnection: {conn}\r\n\r\n",
        body.len()
    )
    .into_bytes();
    r.extend_from_slice(body);
    r
}

fn serve(mut s: TcpStream, cfg: Arc<Config>) {
    let _ = s.set_nodelay(true);
    let mut buf: Vec<u8> = Vec::with_capacity(4096);
    let mut tmp = [0u8; 16 * 1024];
    let mut served = 0u64;
    loop {
        let end = loop {
            if let Some(p) = buf.windows(4).position(|w| w == b"\r\n\r\n") {
                break p;
            }
            match s.read(&mut tmp) {
                Ok(0) | Err(_) => return,
                Ok(n) => buf.extend_from_slice(&tmp[..n]),
            }
        };
        let head = String::from_utf8_lossy(&buf[..end]).into_owned();
        buf.drain(..end + 4);
        let path = head
            .strip_prefix("GET ")
            .and_then(|r| r.split(' ').next())
            .unwrap_or("")
            .to_string();
        served += 1;
        let close = cfg.max_requests > 0 && served >= cfg.max_requests;
        if !cfg.delay.is_zero() {
            thread::sleep(cfg.delay);
        }
        let resp = match cfg.files.get(&path) {
            Some(body) => response(body, 200, close),
            None => response(b"<html>not found</html>", 404, close),
        };
        if s.write_all(&resp).is_err() || close {
            return;
        }
    }
}

fn main() {
    let (mut root, mut bind, mut port) = ("data/pages".to_string(), "127.0.0.1".to_string(), 8080u16);
    let (mut delay_us, mut max_requests) = (0u64, 0u64);
    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        let v = args.next().unwrap_or_default();
        match a.as_str() {
            "--root" => root = v,
            "--bind" => bind = v,
            "--port" => port = v.parse().expect("--port"),
            "--delay-us" => delay_us = v.parse().expect("--delay-us"),
            "--max-requests" => max_requests = v.parse().expect("--max-requests"),
            _ => {
                eprintln!(
                    "usage: static_server --root DIR [--bind ADDR] [--port P] [--delay-us N] [--max-requests N]"
                );
                std::process::exit(2);
            }
        }
    }
    // Files are served under the name of the root directory; for example,
    // data/pages/x.html is served as /pages/x.html.
    let root_path = Path::new(&root);
    let prefix = format!("/{}", root_path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_default());
    let mut files = HashMap::new();
    if let Err(e) = load_dir(root_path, &prefix, &mut files) {
        eprintln!("cannot load {root}: {e}");
        std::process::exit(1);
    }
    if files.is_empty() {
        eprintln!("no files under {root}");
        std::process::exit(1);
    }
    let listener = TcpListener::bind((bind.as_str(), port)).unwrap_or_else(|e| {
        eprintln!("cannot bind {bind}:{port}: {e}");
        std::process::exit(1);
    });
    eprintln!(
        "static_server: {} files under {prefix}/ on {bind}:{port} (delay {delay_us} us, max-requests {max_requests})",
        files.len()
    );
    let cfg = Arc::new(Config { delay: Duration::from_micros(delay_us), max_requests, files });
    for conn in listener.incoming() {
        match conn {
            Ok(s) => {
                let cfg = Arc::clone(&cfg);
                thread::spawn(move || serve(s, cfg));
            }
            Err(e) => eprintln!("accept: {e}"),
        }
    }
}
