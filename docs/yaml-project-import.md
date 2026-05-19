# YAML Project Import

Project setup should be possible from a YAML file so a convention can bootstrap
its basic structure quickly.

## Example

```yaml
project:
  name: Awoostria 2026
  slug: awoostria-2026
  timezone: Europe/Vienna
  opens_at: 2026-07-22T10:00:00+02:00
  closes_at: 2026-07-25T23:00:00+02:00

accounts:
  - email: marton.pornoi@gmail.com
    roles: [Admin, Board, Event Manager]

roles:
  - Admin
  - Board
  - Event Manager
  - Security
  - Fursuit Support
  - Themeing

hotels:
  - name: Main Convention Hotel
    rooms:
      - name: Main Stage
        capacity: 500
        properties: [stage, projector, sound, lights]
      - name: Panel Room A
        capacity: 80
        properties: [projector, movable_wall]
      - name: Panel Room B
        capacity: 80
        properties: [projector, movable_wall]
    combinations:
      - name: Panel Room A+B
        rooms: [Panel Room A, Panel Room B]
        capacity: 170

subprojects:
  - name: Event Submissions
    slug: events
    kind: event_submission
    form:
      sections:
        - title: Display
          fields:
            - label: Display - Title
              type: short_text
              required: true
            - label: Display - Subtitle (optional)
              type: short_text
            - label: Display - Abstract
              type: long_text
              required: true
            - label: Display - Duration
              type: duration
              required: true
        - title: Mapping
          fields:
            - label: Mapping - Estimated Headcount
              type: single_choice
              options: [S, M, L, XXXL]
            - label: Mapping - Room Layout
              type: multi_choice
              options: [Theater, U-Shape, Cabaret, Exhibit, Activity, Empty]

  - name: Dance Competition Volunteers
    slug: dance-volunteers
    kind: volunteer_registration
    form:
      sections:
        - title: Volunteer Details
          fields:
            - label: Preferred Role
              type: single_choice
              options: [Check-in, Backstage, Music Desk, Runner]
            - label: Availability
              type: availability_grid

timetable:
  rounds:
    - key: private_placement
      label: Host private placement
    - key: host_negotiation
      label: Host negotiation
    - key: public
      label: Public timetable
  layers:
    - panels
    - volunteer_shifts
    - signage
```

## Import Rules

- Existing slugs should update matching records, not create duplicates.
- Deleting records from YAML should require an explicit destructive flag.
- Unknown fields should fail validation by default.
- Google Forms labels should be preserved exactly.
- Imports should produce a preview/diff before applying changes.

