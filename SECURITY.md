# Security Policy

Artifact Memory contracts may describe sensitive knowledge and artifacts, but
this repository is not a credential vault or private artifact store.

## Reporting a vulnerability

Do not open a public issue containing exploit details, credentials, private
records, customer material, or sensitive artifact metadata. Report security
concerns through GitHub's private vulnerability reporting feature when it is
available for this repository, or contact the repository owner privately.

## Sensitive-data rule

Never commit:

- passwords, API keys, tokens, cookies, private keys, or signed bearer URLs;
- real customer or private product records;
- machine-local vault paths, endpoint credentials, or resolver configuration;
- raw artifacts, attachments, browser profiles, or AI task archives;
- production logs or fixtures derived from protected material.

If a credential enters Git history, revoke or rotate it immediately before
attempting history repair.

GitHub secret scanning, push protection, vulnerability alerts, and private
vulnerability reporting are enabled. Protected `main` and `dev` branches also
require the public-safety and cross-platform contract checks. The repository's
full-history public-safety check remains a defense-in-depth control in local
development and CI; no scanner proves that private material is safe to publish
without human review of its meaning and provenance.

## Trust boundary

Record validation, content verification, authorization, transport security,
storage custody, and backup recovery are separate concerns. A valid record or
digest does not prove that its claims are true, that its sender is trusted, or
that its receiver is authorized to retrieve referenced content or take action.
