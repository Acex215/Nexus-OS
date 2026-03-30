# NEXUS OS — Public Launch Checklist

Every item must be completed before making the repository public.

## Phase 1: Code Complete
- [x] All behavioral collection channels implemented and tested (Rust, 18 channels)
- [x] Feature extraction (288-dim) working end-to-end
- [x] Privacy pipeline verified (noise, salt, hash)
- [x] Local insight engine producing correct results
- [ ] Sequence predictor training on compound token history
- [ ] Epoch cycle running daily without errors

## Phase 2: Security
- [x] .gitignore comprehensive (Phase A.1)
- [x] Private components removed from tracking (Phase A.2)
- [x] agents/ trimmed to OS-core only (Phase A.3)
- [x] First-boot forces password change (Phase A.5)
- [x] Gateway requires auth for remote connections (Phase A.5)
- [x] ENFORCEMENT_ENABLED defaults to true (Phase A.5)
- [ ] All credentials rotated (docs/CREDENTIAL_ROTATION.md)
- [ ] BFG Repo-Cleaner run on git history
- [ ] No secrets in any tracked file (verify_launch_ready.py)

## Phase 3: Documentation
- [x] README.md (FIN.1)
- [x] CONTRIBUTING.md (FIN.2)
- [x] LICENSE (FIN.3)
- [x] SECURITY.md (FIN.4)
- [x] docs/ARCHITECTURE.md (FIN.5)
- [x] docs/PRIVACY.md (FIN.6)
- [x] docs/CREDENTIAL_ROTATION.md (Phase A.6)
- [x] docs/TOKEN_ECONOMICS.md (existing)

## Phase 4: Testing
- [x] verify_launch_ready.py passes (56 pass, 9 pre-existing issues)
- [x] Behavioral collection tested (Rust collector running 30+ minutes)
- [x] Debug CLI confirms on-chain data is readable
- [x] Feature extraction produces valid 288-dim vector
- [x] Integration test suite passes (30/30)

## Phase 5: Legal
- [ ] Lawyer reviewed docs/PRIVACY.md
- [ ] Lawyer reviewed LICENSE
- [ ] Lawyer approved each of the 18 collection channels
- [ ] Lawyer approved consent flow (first-boot → on-chain)
- [ ] Lawyer approved debug lockout procedure
- [ ] Lawyer confirmed 32-byte hash classification
- [ ] Any required changes from legal review implemented

## Phase 6: Lockout (IRREVERSIBLE — do last)
- [ ] BehavioralActionRegistry.disableDebugMode() called
- [ ] BehavioralActionRegistry.lockAdmin() called
- [ ] Verify: contract.debugMode() returns false
- [ ] Verify: contract.admin() returns 0x0000...
- [ ] ImmutableOS lockout countdown started (optional for V1)

## Phase 7: Launch
- [ ] git push --force (after BFG cleanup)
- [ ] GitHub repo visibility → Public
- [ ] Verify CI passes on GitHub Actions
- [ ] Verify README renders correctly on GitHub
- [ ] Post announcement to venture-verse.org
