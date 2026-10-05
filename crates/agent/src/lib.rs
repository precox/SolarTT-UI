//! Adapter between the independent policy engine and upstream's optional interfaces.
use async_trait::async_trait;
use solartt_policy::{Engine, Session};
use std::{
    collections::HashSet,
    io,
    net::{IpAddr, Ipv4Addr, Ipv6Addr},
    sync::Arc,
};
use trusttunnel::{
    authentication::{Authenticator, Source, Status},
    log_utils::IdChain,
    managed,
};

pub struct Adapter {
    pub engine: Arc<Engine>,
    pub denied_addresses: HashSet<IpAddr>,
}
struct ManagedSession {
    identity: managed::Identity,
    session: Arc<Session>,
    engine: Arc<Engine>,
}
struct ManagedPermit(solartt_policy::Permit);
fn credentials<'a>(source: &'a Source<'_>) -> &'a str {
    match source {
        Source::ProxyBasic(s) | Source::Sni(s) => s.as_ref(),
    }
}
fn denied() -> io::Error {
    io::Error::new(io::ErrorKind::PermissionDenied, "Access denied")
}

impl Authenticator for Adapter {
    fn authenticate(&self, source: &Source<'_>, _: &IdChain<u64>) -> Status {
        if self.engine.authenticate(credentials(source)).is_some() {
            Status::Pass
        } else {
            Status::Reject
        }
    }
    fn username(&self, source: &Source<'_>) -> Option<String> {
        self.engine
            .authenticate(credentials(source))
            .map(|i| i.user_id)
    }
}
impl managed::Policy for Adapter {
    fn allows_destination(&self, ip: IpAddr) -> bool {
        // IPv6 forwarding is outside the initial managed scope, including UDP.
        if ip.is_ipv6() {
            return false;
        }
        !self.denied_addresses.contains(&ip)
    }
    fn resolve(&self, source: &Source<'_>) -> io::Result<managed::Identity> {
        let i = self
            .engine
            .authenticate(credentials(source))
            .ok_or_else(denied)?;
        Ok(managed::Identity {
            user_id: i.user_id,
            credential_id: i.credential_id,
            generation: i.generation,
        })
    }
    fn open(&self, identity: managed::Identity) -> io::Result<Arc<dyn managed::Session>> {
        let session = self
            .engine
            .open_session(solartt_policy::Identity {
                user_id: identity.user_id.clone(),
                credential_id: identity.credential_id.clone(),
                generation: identity.generation,
            })
            .map_err(|_| denied())?;
        Ok(Arc::new(ManagedSession {
            identity,
            session,
            engine: self.engine.clone(),
        }))
    }
}
#[async_trait]
impl managed::Session for ManagedSession {
    fn identity(&self) -> &managed::Identity {
        &self.identity
    }
    fn is_cancelled(&self) -> bool {
        self.session.is_cancelled()
    }
    async fn cancelled(&self) {
        self.session.cancelled().await;
    }
    async fn reserve(&self, bytes: usize, datagram: bool) -> io::Result<Box<dyn managed::Permit>> {
        self.engine
            .reserve(&self.session, bytes, datagram)
            .await
            .map(|p| Box::new(ManagedPermit(p)) as _)
    }
}
impl managed::Permit for ManagedPermit {
    fn amount(&self) -> usize {
        self.0.amount()
    }
    fn begin(&mut self) {
        self.0.begin();
    }
    fn finish(self: Box<Self>, accepted: usize) -> io::Result<()> {
        self.0.finish(accepted)
    }
}

/// Snapshot addresses assigned to local interfaces. Production also supplies
/// public/NAT addresses explicitly; this function never changes networking.
pub fn local_addresses() -> io::Result<HashSet<IpAddr>> {
    struct List(*mut libc::ifaddrs);
    impl Drop for List {
        fn drop(&mut self) {
            unsafe { libc::freeifaddrs(self.0) };
        }
    }
    let mut pointer = std::ptr::null_mut();
    if unsafe { libc::getifaddrs(&mut pointer) } != 0 {
        return Err(io::Error::last_os_error());
    }
    let list = List(pointer);
    let mut cursor = list.0;
    let mut addresses = HashSet::new();
    while !cursor.is_null() {
        let interface = unsafe { &*cursor };
        if !interface.ifa_addr.is_null() {
            match unsafe { (*interface.ifa_addr).sa_family } as i32 {
                libc::AF_INET => {
                    let address = unsafe { &*(interface.ifa_addr as *const libc::sockaddr_in) };
                    addresses.insert(IpAddr::V4(Ipv4Addr::from(
                        address.sin_addr.s_addr.to_ne_bytes(),
                    )));
                }
                libc::AF_INET6 => {
                    let address = unsafe { &*(interface.ifa_addr as *const libc::sockaddr_in6) };
                    addresses.insert(IpAddr::V6(Ipv6Addr::from(address.sin6_addr.s6_addr)));
                }
                _ => {}
            }
        }
        cursor = interface.ifa_next;
    }
    Ok(addresses)
}
