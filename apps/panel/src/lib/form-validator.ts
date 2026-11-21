// Shared rjsf validator with ajv's own error messages localized to Spanish:
// without a localizer rjsf/ajv render things like "must be string" in English,
// inconsistent with the rest of the panel.
import { customizeValidator } from "@rjsf/validator-ajv8";
import es from "ajv-i18n/localize/es";

export const validator = customizeValidator({}, es);
