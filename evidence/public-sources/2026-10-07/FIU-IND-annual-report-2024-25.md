# Evidence note: FIU-IND Annual Report 2024-25

A public source read on 2026-10-07 for the problem and stakes in `docs/REAL_WORLD_FIT.md`. The report itself is not stored in this repository: it is 138 MB and the publisher's work. This note says where it is and how to check the copy that was read.

| | |
|---|---|
| Source | Financial Intelligence Unit, India (FIU-IND), Annual Report 2024-25: https://fiuindia.gov.in/pdfs/downloads/AnnualReport2024_25.pdf (listed on https://fiuindia.gov.in/files/Publication/Publication.html) |
| Copy read | Downloaded with `curl` on 2026-10-07. 138,071,469 bytes, equal to the server's stated length. 112 pages |
| SHA-256 | `bd6b93046ddef7f12c46be4fc2e09a334cb64717ab4ba656995595ad7e857c7a`. Download the file again and compare; if it differs, the publisher has replaced it |
| Page numbers | Printed page = PDF page minus 6. Both are given below |
| How it was read | The text layer was extracted with a PDF library. 26 of the 112 pages have no text layer and were **not read**. The pages marked "image" were rendered and read directly, because the extracted text of a chart or a layout page can be jumbled |

## What was read

| Fact (numbers as the report prints them, then in standard grouping) | Printed page (PDF page) | Read from |
|---|---|---|
| Suspicious transaction reports filed: FY 2022-23 6,45,905 (645,905); FY 2023-24 3,68,592 (368,592); FY 2024-25 4,34,668 (434,668) | 20 (26) | image |
| Highlights for the year, reports filed: CTRs 1,73,13,368; CBWTRs 1,02,73,512; NTRs 9,31,548; CCRs 2,09,644; STRs 4,34,668 | 5 (11) | text layer, and consistent with page 20 |
| 6,908 priority STRs were disseminated to law-enforcement agencies in FY 2024-25. The report says that over the last four years about 40% of priority STRs were found useful | 5 and 22 (11 and 28) | text layer |
| Feedback from law-enforcement agencies is used, the report says, to improve the overall quality of the reports reporting entities submit | 23 (29) | text layer |
| Compliance action: 8 orders issued, 5 cases with a monetary penalty, an aggregate penalty of Rs.30,48,65,000, and 8 cases with specific directions | 50 (56) | image |
| A case against a commercial bank. The report lists violations of Section 12(1) of the PMLA and of the PML Rules, including Rule 3(1)(D) and Rule 7(3) for deficient alert management and Rule 8(2) for non-filing of STRs. The penalty was Rs.1,66,25,000. The directions required the bank to strengthen its transaction monitoring, resolve alerts within prescribed timelines, and certify its remedial action within 90 days | 50 and 51 (56 and 57) | image |

## What this does not establish

- It says nothing about how any institution documents the reasons for a decision on an alert, or whether that was part of the case above. The report names deficient alert management and non-filing; it does not name the written rationale. The description of current practice in the writeup stays ASSUMED.
- It does not verify any rule in the corpus. INS-004 (templated narratives) was searched for in the pages with a text layer and not found, so it stays NEEDS-VERIFICATION.
- The figures are the publisher's, read once by the author of this repository with the method above. They were not independently checked.
