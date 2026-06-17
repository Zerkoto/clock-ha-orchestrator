# Clock API Mapping

## Official Sources Checked

- Clock PMS+ developer article "2. Check the API specs" says Clock provides `PMS API` for hotel functionality such as bookings, guests, rooms and rates, and points integrators to the Clock PMS+ API Docs Postman collection.
- The public Postman documentation says access uses `api_user` and `api_key` with Digest access authentication.
- The Postman collection documents the URL pattern using region, API type, subscription ID and account ID, for example `sky-eu1.clock-software.com/{api_type}/{subscription_id}/{account_id}`.
- The Postman collection states filter parameters support operators such as `eq`, `not_eq`, `gt`, `gteq`, `lt` and `lteq`, and that only first-level object attributes can be filtered.
- The Postman collection states the API rate limit is 5 calls per second per API user and recommends retrying `HTTP 429 Too Many Requests` with backoff.
- The Postman collection describes message channels via Pull, Push and SQS and lists booking events including `booking_new`, `booking_update`, `booking_expected`, `booking_checked_in`, `booking_checked_out`, `booking_canceled` and `booking_no_show`.

## Live Adapter Status

The current code intentionally does not hard-code Clock booking or room endpoint paths, pagination keys or physical-room fields. Set these only after one of the following is available:

- A direct official Postman endpoint reference for the relevant PMS API route.
- A sanitized sandbox payload committed under `tests/fixtures/clock/`.
- A documented field mapping reviewed in this file.

Required environment variables for enabling live adapter behavior:

```text
CLOCK_BOOKINGS_ENDPOINT_PATH=
CLOCK_ROOMS_ENDPOINT_PATH=
CLOCK_ENDPOINT_DOC_REFERENCE=
```

## Required Normalized Fields

The app only stores automation-relevant fields:

```text
property_id
clock_booking_id
booking_number
external_source
external_reference
booking_status
arrival_date
departure_date
created_at
updated_at
status_changed_at
room_type_id
room_type_name
physical_room_id
physical_room_number
adults
children
first_seen_at
last_seen_at
payload_hash
```

Do not store guest email, phone, address, notes, identity-document data, payment card data or guest names unless a later approved requirement changes the privacy model.

## Pending Sandbox Questions

- Exact booking list endpoint for incremental polling.
- Exact booking detail endpoint needed for booking events.
- Pagination mechanism and cursor/page fields.
- Physical room identifier and physical room number fields on booking payloads.
- Room inventory endpoint and stable room ID field.
- Confirmed first-level fields suitable for `updated_at.gteq` filtering.

