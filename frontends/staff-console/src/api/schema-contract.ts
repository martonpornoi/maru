import type { components } from "./schema";

type Assert<Condition extends true> = Condition;
type IsRequired<Schema, Key extends keyof Schema> = object extends Pick<
  Schema,
  Key
>
  ? false
  : true;

type CharityPartnerUpdate =
  components["schemas"]["PatchedCharityPartnerUpdate"];
type VenuePropertyUpdate = components["schemas"]["PatchedVenuePropertyUpdate"];

export type CharityPartnerExpectedVersionIsRequired = Assert<
  IsRequired<CharityPartnerUpdate, "expected_version">
>;
export type CharityPartnerReasonIsRequired = Assert<
  IsRequired<CharityPartnerUpdate, "reason">
>;
export type VenuePropertyExpectedVersionIsRequired = Assert<
  IsRequired<VenuePropertyUpdate, "expected_version">
>;
export type VenuePropertyReasonIsRequired = Assert<
  IsRequired<VenuePropertyUpdate, "reason">
>;
