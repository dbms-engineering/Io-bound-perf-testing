//! crawler: performs a single measured run of one crawler implementation.
//!
//! ```text
//! crawler --mode process|thread|event --urls data/urls.txt
//!         [--host 127.0.0.1] [--port 8080] [--seed N] [--no-shuffle]
//!         [--workers 16] [--threads 2] [--conns 8]
//! ```
//!
//! Prints a single JSON object to stdout. `wall_ns` is measured with a
//! monotonic clock around the crawl only; reading and shuffling the URL list
//! are excluded. The counters allow the harness to verify that every variant
//! performed the same work.

use std::process::ExitCode;
use std::time::Instant;

use io_bound_perf::common::{read_urls, shuffle_urls, Target};
use io_bound_perf::crawlers::{Crawler, EventLoop, ProcessPool, ThreadPool};

const BUILD_TAG: &str = match option_env!("CRAWLER_BUILD_TAG") {
    Some(t) => t,
    None => "dev",
};

fn usage() -> ! {
    eprintln!(
        "usage: crawler --mode process|thread|event --urls FILE [--host H] [--port P]\n\
         \x20              [--seed N] [--no-shuffle] [--workers W] [--threads M] [--conns N]"
    );
    std::process::exit(2);
}

fn main() -> ExitCode {
    let mut mode = String::new();
    let mut urls_file = String::new();
    let mut host = "127.0.0.1".to_string();
    let (mut port, mut seed, mut shuffle) = (8080u16, 0u64, true);
    let (mut workers, mut threads, mut conns) = (16usize, 2usize, 8usize);

    let mut args = std::env::args().skip(1);
    while let Some(a) = args.next() {
        let mut val = || args.next().unwrap_or_else(|| usage());
        match a.as_str() {
            "--mode" => mode = val(),
            "--urls" => urls_file = val(),
            "--host" => host = val(),
            "--port" => port = val().parse().unwrap_or_else(|_| usage()),
            "--seed" => seed = val().parse().unwrap_or_else(|_| usage()),
            "--workers" => workers = val().parse().unwrap_or_else(|_| usage()),
            "--threads" => threads = val().parse().unwrap_or_else(|_| usage()),
            "--conns" => conns = val().parse().unwrap_or_else(|_| usage()),
            "--no-shuffle" => shuffle = false,
            _ => usage(),
        }
    }
    if mode.is_empty() || urls_file.is_empty() {
        usage();
    }

    let target = match Target::resolve(&host, port) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("cannot resolve {host}:{port}: {e}");
            return ExitCode::from(1);
        }
    };
    let crawler: Box<dyn Crawler> = match mode.as_str() {
        "process" => Box::new(ProcessPool { target, workers }),
        "thread" => Box::new(ThreadPool { target, workers }),
        "event" => Box::new(EventLoop { target, threads, conns }),
        _ => usage(),
    };
    let mut urls = match read_urls(&urls_file) {
        Ok(u) => u,
        Err(e) => {
            eprintln!("cannot read {urls_file}: {e}");
            return ExitCode::from(1);
        }
    };
    if shuffle {
        shuffle_urls(&mut urls, seed);
    }

    let t0 = Instant::now();
    let s = crawler.run(&urls);
    let ns = t0.elapsed().as_nanos();

    println!(
        "{{\"crawler\":\"{}\",\"build\":\"{}\",\"seed\":{},\"urls\":{},\"wall_ns\":{},\
         \"pages\":{},\"bytes\":{},\"tags\":{},\"errors\":{}}}",
        crawler.name(),
        BUILD_TAG,
        seed,
        urls.len(),
        ns,
        s.pages,
        s.bytes,
        s.tags,
        s.errors
    );
    if s.errors == 0 {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(3)
    }
}
