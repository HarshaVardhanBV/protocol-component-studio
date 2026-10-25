# data/

Public clinical-trial documents used for extraction, the cross-document demo, and the gold set.

## Layout — group by ASSET, not by document type
The asset (one drug/trial) is the unit the whole project hangs off: the same component can
appear in that asset's protocol, SAP, CSR, label… so there's one folder per asset, and the
document **type** is the tag at the end of each filename (`… - Protocol.pdf`, `… - SAP.pdf`).
That trailing type is what the loader keys on — the long descriptive prefix is just for humans.

```
data/
  pfizer_c4591001/
    … (NCT04368728) - Protocol.pdf
    … (NCT04368728) - SAP.pdf
    … (NCT04368728) - Interim CSR.pdf
    … (NCT04368728) - FDA briefing.pdf
  moderna_cove/
    … (NCT04470427) - Protocol.pdf
    … (NCT04470427) - SAP.pdf
    … (NCT04470427) - ICF.pdf
    … (NCT04470427) - Primary Results.pdf
  recovery/
    … ISRCTN50189673 - Protocol.pdf
    … ISRCTN50189673 - Protocol old.pdf     # earlier version (for the change-impact / versioning demo)
    … ISRCTN50189673 - SAP.pdf
```

Naming convention: `<asset label> - <DocType>.pdf`, where `<DocType>` ∈
{Protocol, SAP, CSR, ICF, FDA briefing, Primary Results}. For versioned docs, keep an
explicit marker (e.g. `… - Protocol old.pdf`).

## Sources (all public)
- **Pfizer–BioNTech Comirnaty, C4591001 (NCT04368728):** protocol + SAP from ClinicalTrials.gov Study Documents; interim CSR via UK Parliament deposit; FDA advisory-committee briefing.
- **Moderna Spikevax, COVE / mRNA-1273-P301 (NCT04470427):** protocol + SAP + ICF from ClinicalTrials.gov; primary results from NEJM.
- **RECOVERY (ISRCTN50189673):** protocol (two versions) + SAP from recoverytrial.net.

Public-data only. Vaccine protocols are long (100+ pages); a short RCT protocol from the
*Trials* journal or BMJ Open is a gentler first extraction target.
