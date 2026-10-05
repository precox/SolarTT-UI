//! Regression for RUSTSEC-2026-0258: test the actual resolved h2 implementation
//! with raw frames, bypassing the well-behaved client's outbound validation.
use tokio::io::{AsyncReadExt, AsyncWriteExt};

#[tokio::test]
async fn unread_body_empty_data_flood_is_rejected_with_bounded_frame_budget() {
    let (mut client, server) = tokio::io::duplex(65536);
    let receiver = tokio::spawn(async move {
        let mut connection = h2::server::handshake(server).await.unwrap();
        // Keep the body alive and unread while driving the connection.
        let (request, respond) = connection.accept().await.unwrap().unwrap();
        let error = match connection.accept().await {
            Some(Err(error)) => error,
            _ => panic!("Empty DATA flood was not rejected"),
        };
        assert_eq!(error.reason(), Some(h2::Reason::ENHANCE_YOUR_CALM));
        drop((request, respond));
    });
    client
        .write_all(b"PRI * HTTP/2.0\r\n\r\nSM\r\n\r\n")
        .await
        .unwrap();
    client
        .write_all(&[0, 0, 0, 4, 0, 0, 0, 0, 0])
        .await
        .unwrap(); // SETTINGS
                   // HPACK: :method POST, :path /, :scheme https, literal :authority example.org.
    let block = b"\x83\x84\x87\x01\x0bexample.org";
    client
        .write_all(&[0, 0, block.len() as u8, 1, 4, 0, 0, 0, 1])
        .await
        .unwrap();
    client.write_all(block).await.unwrap();
    let (mut read, mut write) = tokio::io::split(client);
    let drain = tokio::spawn(async move {
        let mut buffer = [0; 4096];
        while read.read(&mut buffer).await.is_ok_and(|n| n != 0) {}
    });
    let flood = tokio::spawn(async move {
        for _ in 0..100_000 {
            if write.write_all(&[0, 0, 0, 0, 0, 0, 0, 0, 1]).await.is_err() {
                break;
            }
        }
    });
    let result = tokio::time::timeout(std::time::Duration::from_secs(5), receiver).await;
    flood.abort();
    drain.abort();
    result
        .expect("Frame flood did not terminate within the bound")
        .unwrap();
}
