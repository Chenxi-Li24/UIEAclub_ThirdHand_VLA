# Source Snapshot Migration And Risk Summary

Status: source collection completed; normalized service promotion not yet started.

## Authorized Action

The user approved a non-destructive copy into `/home/nieqingcao/ThirdHand/UIEAclub_ThirdHand_VLA`, while keeping every old project unchanged and preserving the new checkout's GitHub association.

## Copy Result

| Classification | Snapshot | Approximate size | Next promotion |
|---|---|---:|---|
| Active | `migration/sources/startouch-web-vla` | 4.9 MB | Robot service, maintenance console, selected web/VLA code |
| Active | `migration/sources/language` | 5.0 MB | 9983 web and 3004 ASR/TTS service |
| Active | `migration/sources/vision-grasp` | 2.7 MB | XVisio, stable identity, supervision and grasp |
| Prototype | `migration/sources/policy-act` | 296 KB | ACT contract/loader boundary; unavailable without checkpoint |
| Historical | `archive/source-snapshots/th-fanxy` | 27 MB | Reference only; never imported formally |

## Risks And Controls

- **Dirty source state:** several inputs contain accepted uncommitted work. Provenance records the observed state; snapshots are copied, never reset.
- **Duplicate implementations:** snapshots are non-runtime inputs. Promotion plans must choose one owner per behavior and add tests before activating it.
- **Secret or payload leakage:** `.env`, API keys, environments, models, weights, logs, captures, artifacts and nested Git metadata were excluded. A tracked-file audit is required before push.
- **Hardware movement:** snapshot collection and foundation tests never open CAN or initialize the Startouch SDK. Real service activation remains separately authorization-gated.
- **Port collision:** current 3000 service remains running. New validation continues on alternate ports until explicit cutover approval.
- **Licensing:** Startouch, XVisio and ASR model redistribution remains unconfirmed. Physical files stay under ignored `local/`; Git contains only hashes and provenance.
- **Policy maturity:** VLA, ACT and DP stay unavailable without complete, reviewed model assets and runtime acceptance.

## Next Plans

Promote and verify Robot, Vision/Supervisor, Speech/Web, orchestration/authorization, semantic Skills, and policy boundaries in separate changes. No snapshot may become a hidden production dependency.
