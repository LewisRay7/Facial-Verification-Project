# ExamVerify Presentation Readiness

## Ten Minutes Before Presenting

1. Connect the laptop to power and stable internet.
2. Connect the Android phone and confirm camera permissions.
3. Run `PRESENTATION_PREFLIGHT.ps1`.
4. Open the desktop app once so Render and Neon are warm.
5. Confirm OTP email delivery before the panel arrives.
6. Use a prepared active session with two face-enrolled eligible students.
7. Keep one registered-but-not-eligible student ready for the denial demo.
8. Do not tune thresholds during the presentation.

## Recommended Demo Sequence

1. Sign in using password and email OTP.
2. Show two active exam sessions and assigned invigilators.
3. Open one selected session and show its imported eligible roster.
4. Verify an eligible student.
5. Scan the same student again and show `ALREADY VERIFIED`, invigilator, and device.
6. Scan a registered student outside the selected session and show access denied.
7. Show the session-specific verification log and evaluation metrics.

## Strong Defense Explanation

Face recognition answers: **Who is this person?**

The selected exam-session roster answers: **Is this person authorized to write
this specific examination?**

Administrators prepare sessions and eligibility lists before the examination.
Invigilators select their assigned active session. Neon/PostgreSQL is the online
authority, so multiple devices can verify concurrently without mixing rosters,
and an atomic attendance update prevents duplicate entry in the same session.

## Honest Limitations

- Face recognition accuracy depends on lighting, camera quality, pose, and the
  quality of enrollment images.
- Offline mode is a last-resort fallback and cannot guarantee cross-device
  duplicate prevention until synchronization.
- The prototype does not integrate directly with a university registrar/SIS;
  CSV/XLSX eligibility import represents that integration boundary.
- Liveness checks reduce spoofing risk but no software-only liveness system is
  perfect against every advanced presentation attack.
- The Flutter developer settings include a fixed-credential offline prototype
  fallback. Use the online cloud login for the presentation; production
  deployment should replace this fallback with securely provisioned,
  device-bound offline credentials or disable it entirely.

## Likely Panel Questions

**Why not approve every registered student?**  
Registration proves institutional identity. The exam-session roster provides
course-specific authorization.

**How do repeat or deferred students enter?**  
An administrator adds them as an explicit exception with a reason.

**How do multiple invigilators avoid duplicate verification?**  
The cloud conditionally changes attendance from not verified to verified.
Only one concurrent request succeeds; later requests return already verified.

**Does importing a list create faces?**  
No. Imports only link student identifiers to existing biometric profiles.

**What protects biometric records?**  
Cloud portraits and biometric profiles are encrypted using AES-256-GCM, with
portrait integrity hashes and role-controlled access.
