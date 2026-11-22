//! Crawlers for the statistics-based performance methodology of
//! Sultanov et al., "A statistics-based performance testing methodology:
//! a case study for the I/O bound tasks", IEEE CSIT 2022.
//!
//! The crawlers in the paper are written in C++; this crate is a Rust port of
//! the same design. All crawlers share a common "abstract crawler"
//! infrastructure (URL loading, seeded shuffling, an HTTP/1.1 client on plain
//! sockets, and a simulated HTML parser), so they differ only in their
//! concurrency model:
//!
//! 1. [`crawlers::ProcessPool`]: worker processes created with `fork()`, blocking sockets.
//! 2. [`crawlers::ThreadPool`]: OS threads, blocking sockets.
//! 3. [`crawlers::EventLoop`]: M:N model in which each of M threads multiplexes
//!    N non-blocking connections through `mio` (epoll on Linux, kqueue on macOS).

pub mod common;
pub mod crawlers;
pub mod http;
