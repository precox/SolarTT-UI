//! Calendar boundaries follow a fixed database timezone, independently of clients.
use crate::Error;
use chrono::{Datelike, Duration, LocalResult, NaiveDate, TimeZone, Utc};
use chrono_tz::Tz;

pub fn period(zone: Tz, timestamp: i64) -> Result<(String, i64), Error> {
    let instant = Utc
        .timestamp_opt(timestamp, 0)
        .single()
        .ok_or(Error::Invalid("Invalid calendar timestamp"))?;
    let local = instant.with_timezone(&zone);
    let (year, month) = if local.month() == 12 {
        (local.year() + 1, 1)
    } else {
        (local.year(), local.month() + 1)
    };
    let mut boundary = NaiveDate::from_ymd_opt(year, month, 1)
        .and_then(|d| d.and_hms_opt(0, 0, 0))
        .ok_or(Error::Invalid("Calendar boundary is out of range"))?;
    // Some IANA zones historically skip midnight or a whole date. Choose the
    // first valid minute; on overlap, choose the earlier instant exactly once.
    for _ in 0..=48 * 60 {
        let resolved = match zone.from_local_datetime(&boundary) {
            LocalResult::Single(t) => Some(t),
            LocalResult::Ambiguous(a, b) => Some(a.min(b)),
            LocalResult::None => None,
        };
        if let Some(next) = resolved {
            return Ok((
                format!("calendar-{:04}-{:02}", local.year(), local.month()),
                next.timestamp(),
            ));
        }
        boundary += Duration::minutes(1);
    }
    Err(Error::Invalid("Unable to resolve calendar boundary"))
}
#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn month_end_year_end_and_dst_boundaries() {
        let at = Utc
            .with_ymd_and_hms(2026, 10, 31, 20, 59, 59)
            .unwrap()
            .timestamp();
        let (key, next) = period(chrono_tz::Europe::Moscow, at).unwrap();
        assert_eq!(key, "calendar-2026-10");
        assert_eq!(
            next,
            Utc.with_ymd_and_hms(2026, 10, 31, 21, 0, 0)
                .unwrap()
                .timestamp()
        );
        assert_eq!(
            period(chrono_tz::Europe::Moscow, next).unwrap().0,
            "calendar-2026-11"
        );
        let at = Utc
            .with_ymd_and_hms(2026, 12, 31, 22, 0, 0)
            .unwrap()
            .timestamp();
        assert_eq!(
            period(chrono_tz::Europe::Moscow, at).unwrap().0,
            "calendar-2027-01"
        );
        let at = Utc
            .with_ymd_and_hms(2026, 3, 20, 0, 0, 0)
            .unwrap()
            .timestamp();
        assert_eq!(
            period(chrono_tz::Europe::Berlin, at).unwrap().1,
            Utc.with_ymd_and_hms(2026, 3, 31, 22, 0, 0)
                .unwrap()
                .timestamp()
        );
    }
}
