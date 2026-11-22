//! Input handling and the simulated parser shared by all crawlers.

use std::collections::HashMap;
use std::fs;
use std::io;
use std::net::{SocketAddr, ToSocketAddrs};

/// Aggregated result of a crawl. The struct is `repr(C)` so that a child
/// process can send it through a pipe as raw bytes.
#[repr(C)]
#[derive(Debug, Default, Clone, Copy, PartialEq, Eq)]
pub struct CrawlStats {
    /// Successfully downloaded pages (HTTP 200).
    pub pages: u64,
    /// Body bytes received.
    pub bytes: u64,
    /// Tags found by the simulated parser.
    pub tags: u64,
    /// Pages that could not be fetched after all retries.
    pub errors: u64,
}

impl CrawlStats {
    pub fn add(&mut self, o: &CrawlStats) {
        self.pages += o.pages;
        self.bytes += o.bytes;
        self.tags += o.tags;
        self.errors += o.errors;
    }
}

/// The HTTP server being crawled.
#[derive(Debug, Clone)]
pub struct Target {
    pub host: String,
    pub addr: SocketAddr,
}

impl Target {
    pub fn resolve(host: &str, port: u16) -> io::Result<Target> {
        let addr = (host, port)
            .to_socket_addrs()?
            .find(|a| a.is_ipv4())
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "host has no IPv4 address"))?;
        Ok(Target { host: host.to_string(), addr })
    }
}

/// Maximum number of attempts per URL (the server may close a keep-alive connection).
pub const MAX_ATTEMPTS: u32 = 3;

/// Reads one URL path per line. Blank lines and `#` comments are ignored.
pub fn read_urls(path: &str) -> io::Result<Vec<String>> {
    let text = fs::read_to_string(path)?;
    Ok(text
        .lines()
        .map(str::trim)
        .filter(|l| !l.is_empty() && !l.starts_with('#'))
        .map(|l| if l.starts_with('/') { l.to_string() } else { format!("/{l}") })
        .collect())
}

/// SplitMix64 pseudo-random number generator. It is small, well distributed,
/// and produces identical output on every platform, so a seed recorded in the
/// results always reproduces the same URL order.
pub struct SplitMix64(u64);

impl SplitMix64 {
    pub fn new(seed: u64) -> Self {
        SplitMix64(seed)
    }
    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
}

/// Randomizes the input order with a Fisher-Yates shuffle (paper Sec. III-A-1).
pub fn shuffle_urls(urls: &mut [String], seed: u64) {
    let mut rng = SplitMix64::new(seed);
    for i in (1..urls.len()).rev() {
        let j = (rng.next_u64() % (i as u64 + 1)) as usize;
        urls.swap(i, j);
    }
}

/// Splits `0..n` into `parts` contiguous, nearly equal half-open ranges.
pub fn split_ranges(n: usize, parts: usize) -> Vec<(usize, usize)> {
    let parts = parts.max(1);
    let (base, extra) = (n / parts, n % parts);
    let mut begin = 0;
    (0..parts)
        .map(|i| {
            let len = base + usize::from(i < extra);
            let r = (begin, begin + len);
            begin += len;
            r
        })
        .collect()
}

/// Simulates HTML parsing by collecting tags (paper Sec. II). Counts opening
/// tags and accumulates their frequencies. Closing tags, comments, doctypes,
/// and processing instructions are skipped.
pub fn collect_tags(html: &[u8], freq: &mut HashMap<String, u32>) -> u64 {
    let mut count = 0;
    let mut i = 0;
    let n = html.len();
    let mut name = String::with_capacity(16);
    while i < n {
        match html[i..].iter().position(|&b| b == b'<') {
            None => break,
            Some(p) => i += p + 1,
        }
        if i >= n || !html[i].is_ascii_alphabetic() {
            continue; // Closing tag, comment, doctype, processing instruction, or stray '<'.
        }
        name.clear();
        while i < n && (html[i].is_ascii_alphanumeric() || html[i] == b'-') {
            name.push(html[i].to_ascii_lowercase() as char);
            i += 1;
        }
        match freq.get_mut(name.as_str()) {
            Some(v) => *v += 1,
            None => {
                freq.insert(name.clone(), 1);
            }
        }
        count += 1;
    }
    count
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tags_are_counted() {
        let mut f = HashMap::new();
        let n = collect_tags(b"<!DOCTYPE html><html><body><p class=x>hi</p><img/><!-- c --></body></html>", &mut f);
        assert_eq!(n, 4);
        assert_eq!(f["p"], 1);
        assert_eq!(f["img"], 1);
    }

    #[test]
    fn shuffle_is_deterministic_permutation() {
        let mut a: Vec<String> = (0..100).map(|i| i.to_string()).collect();
        let mut b = a.clone();
        shuffle_urls(&mut a, 42);
        shuffle_urls(&mut b, 42);
        assert_eq!(a, b);
        let mut s = a.clone();
        s.sort_by_key(|x| x.parse::<u32>().unwrap());
        assert_eq!(s, (0..100).map(|i| i.to_string()).collect::<Vec<_>>());
        let mut c = s.clone();
        shuffle_urls(&mut c, 43);
        assert_ne!(a, c);
    }

    #[test]
    fn ranges_cover_everything() {
        let r = split_ranges(10, 3);
        assert_eq!(r, vec![(0, 4), (4, 7), (7, 10)]);
        assert_eq!(split_ranges(2, 4).iter().map(|(a, b)| b - a).sum::<usize>(), 2);
    }
}
