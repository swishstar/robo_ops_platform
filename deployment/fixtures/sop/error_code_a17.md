# Error Code A-17 — Actuator Self-Test Failure

## Summary
Error code **A-17** indicates the actuator self-test failed during pre-release checks.

## Immediate actions
1. Verify the E-stop latch is fully reset and not partially engaged.
2. Run the actuator self-test sequence from the maintenance console.
3. Capture torque readings for each joint before releasing the visit for sign-off.
4. If A-17 persists after a successful self-test, quarantine the unit and escalate to Level-2 field engineering.

## Acceptance criteria
- Actuator self-test completes with PASS.
- Torque readings are logged in the visit findings.
- E-stop latch verified open/reset.

## Citation
Source: /03_Technical_Library/RR-FieldOps/Maintenance_Checklist.pdf (p.12)
