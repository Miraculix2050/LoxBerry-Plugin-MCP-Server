# Analysis semantic evidence

Rules extend the existing pure state resolver. A control name, category,
user-declared profile role or adjacent state never authorizes a decoder.

Primary source: [Loxone Structure File 17.1](https://www.loxone.com/dede/wp-content/uploads/sites/2/2021/10/1701_Structure-File.pdf),
dated 2026-08-06, 168 pages, SHA-256
`97bbc5ec79c8479c0f2f561a55780a764a518fe420d11fd2fc26979fc41e5f23`.
Page references below are one-based PDF pages. Each rule records document and
rule versions; absent firmware evidence remains absent.

| Exact type/state | Meaning and value gate | Source/version | Evidence limit |
| --- | --- | --- | --- |
| `IRoomControllerV2.tempActual` | Finite numeric current temperature | pp.73,76; V2 available since Miniserver 10.0 | Explicit complete Celsius/Fahrenheit format required for a known unit. |
| `IRoomControllerV2.tempTarget` | Finite numeric target temperature | pp.73,76; same gate | Target temperature does not establish heating activity. |
| `InfoOnlyDigital.active` | Numeric zero/one indication | p.72; Structure File 17.1 | No physical appliance, contact or power role is inferred. |
| `Hourcounter.active` | Numeric zero/one counter activity | pp.70–71; Structure File 17.1 | Counter activity does not establish measured energy. |

Authorized read-only type evidence on Loxberry-Test confirmed the exact V2 type
and both temperature states, plus `InfoOnlyDigital.active`. Its V2 format is
`%.1f°`: this proves neither Celsius nor Fahrenheit. Hourcounter coverage is
document/fixture based until an authorized target specimen is tested. Evidence
does not claim support for every firmware version or unknown future variants.

Missing values retain the supported descriptor with unavailable interpretation;
nonfinite numbers, booleans, strings and undocumented binary codes are invalid.
Unknown units remain unknown. Generic analog format strings and arbitrary
`Switch.active` states receive no new technical inference. Current observation
quality remains separate from semantic evidence, and historical coverage is not
inferred from current state readability.
