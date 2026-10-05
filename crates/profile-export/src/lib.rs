//! Explicit official-client profiles. Never send these values to logging or telemetry.
use serde::Serialize;
use trusttunnel_deeplink::{DeepLinkConfig, Protocol};

pub struct Profile {
    pub deeplink: String,
    pub toml: String,
    pub qr_svg: String,
}

pub fn export(
    hostname: &str,
    address: &str,
    username: &str,
    password: &str,
    name: &str,
    dns: Vec<String>,
) -> Result<Profile, String> {
    let config = DeepLinkConfig {
        hostname: hostname.into(),
        addresses: vec![address.into()],
        username: username.into(),
        password: password.into(),
        client_random_prefix: None,
        custom_sni: Some(hostname.into()),
        has_ipv6: false,
        skip_verification: false,
        certificate: None,
        upstream_protocol: Protocol::Http2,
        anti_dpi: false,
        name: Some(name.into()),
        dns_upstreams: dns.clone(),
    };
    let deeplink = trusttunnel_deeplink::encode(&config).map_err(|_| "Profile encoding failed")?;
    let roundtrip =
        trusttunnel_deeplink::decode(&deeplink).map_err(|_| "Profile validation failed")?;
    if roundtrip != config {
        return Err("Profile roundtrip mismatch".into());
    }
    #[derive(Serialize)]
    struct ClientConfig<'a> {
        hostname: &'a str,
        addresses: Vec<&'a str>,
        username: &'a str,
        password: &'a str,
        custom_sni: &'a str,
        has_ipv6: bool,
        skip_verification: bool,
        upstream_protocol: &'a str,
        anti_dpi: bool,
        dns_upstreams: Vec<String>,
    }
    let text = toml::to_string(&ClientConfig {
        hostname,
        addresses: vec![address],
        username,
        password,
        custom_sni: hostname,
        has_ipv6: false,
        skip_verification: false,
        upstream_protocol: "http2",
        anti_dpi: false,
        dns_upstreams: dns,
    })
    .map_err(|_| "TOML encoding failed")?;
    let code = qrcode::QrCode::new(deeplink.as_bytes()).map_err(|_| "Profile too large for QR")?;
    let qr_svg = code
        .render::<qrcode::render::svg::Color>()
        .min_dimensions(240, 240)
        .build();
    Ok(Profile {
        deeplink,
        toml: text,
        qr_svg,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn official_codec_roundtrip_preserves_safe_flags() {
        let p = export(
            "media.example.org",
            "192.0.2.1:443",
            "fixture",
            "synthetic-only",
            "Fixture",
            vec!["1.1.1.1".into()],
        )
        .unwrap();
        let decoded = trusttunnel_deeplink::decode(&p.deeplink).unwrap();
        assert!(!decoded.has_ipv6);
        assert!(!decoded.skip_verification);
        assert_eq!(decoded.upstream_protocol, Protocol::Http2);
        assert_eq!(decoded.custom_sni.as_deref(), Some("media.example.org"));
        let table: toml::Value = toml::from_str(&p.toml).unwrap();
        assert_eq!(table["has_ipv6"].as_bool(), Some(false));
        assert!(p.qr_svg.contains("<svg"));
    }
}
