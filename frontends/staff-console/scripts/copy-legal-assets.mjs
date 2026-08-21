import { copyFileSync } from "node:fs";

const projectLicense = new URL("../../../LICENSE", import.meta.url);
const browserLicense = new URL(
  "../../../src/maru/core/static/staff-console/LICENSE.txt",
  import.meta.url
);

copyFileSync(projectLicense, browserLicense);
