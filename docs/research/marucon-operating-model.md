# MaruCon fictional operating model

Status: Repository-owned fictional reference\
Last updated: 2026-08-22

MaruCon is Maru's fictional convention example. It is not a customer,
partner, imported organization, or claim of affiliation. Its data is authored
for documentation and automated tests and uses reserved `.invalid` contacts.

## Purpose

The example provides a coherent way to demonstrate Maru without borrowing a
real convention's identity, people, organization chart, policies, or public
roster. It exercises two independently governed convention brands:

- **MaruCon**, a general community convention with several annual editions;
- **MaruDance**, a second tenant and edition series used for isolation tests.

Both are deliberately synthetic. Names, dates, capacities, accounts, and
workflows are illustrative rather than operational recommendations.

## Fictional Department starter

`marucon-reference@1` is an immutable repository-owned starter copied into an
empty edition. It contains one operational root, **Convention Coordination**,
and 21 independently authored children:

1. Attendee Services
2. Registration
3. Programme
4. Stage Production
5. Venue Operations
6. Logistics
7. Volunteer Support
8. Safety
9. Accessibility
10. Technology
11. Communications
12. Design & Publications
13. Exhibitors
14. Charity
15. Guest Relations
16. Accommodation
17. Hospitality
18. Finance & Procurement
19. Partnerships
20. Live Operations
21. Archive & Handover

The list is derived from Maru's own product requirements. It is not presented
as a correct structure for every organizer. Applying it creates an
edition-owned copy that may diverge without changing the immutable source.

The Executive Board remains a separate organization-governance aggregate. It
is never copied into the Department tree and does not become implicit
Department authority.

## Data and network boundary

The fixture and tutorial create synthetic people through supported services.
They perform no roster download, public-directory parsing, or external
identity lookup. Websites and email addresses use reserved domains. A future
organizer migration must be separately designed and approved; this fictional
starter is not an import format.
