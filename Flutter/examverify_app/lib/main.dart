import 'dart:convert';
import 'dart:io';
import 'dart:math' as math;
import 'dart:async';
import 'dart:ui';

import 'package:camera/camera.dart' as camera;
import 'package:crypto/crypto.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:google_mlkit_face_detection/google_mlkit_face_detection.dart';
import 'package:image/image.dart' as imglib;
import 'package:http/http.dart' as http;
import 'package:path_provider/path_provider.dart';
import 'package:permission_handler/permission_handler.dart';
import 'package:sqflite_common_ffi/sqflite_ffi.dart';
import 'package:tflite_flutter/tflite_flutter.dart' as tfl;

extension _FirstOrNull<T> on Iterable<T> {
  T? get firstOrNull => isEmpty ? null : first;

  T? firstWhereOrNull(bool Function(T value) test) {
    for (final value in this) {
      if (test(value)) return value;
    }
    return null;
  }
}

void main() {
  runApp(const ExamVerifyApp());
}

class AppConfig {
  static const cloudApiUrl = String.fromEnvironment(
    'EXAMVERIFY_API_URL',
    defaultValue: 'https://examverify-cloud-api.onrender.com',
  );
}

class ExamVerifyApp extends StatelessWidget {
  const ExamVerifyApp({
    this.skipPersistence = false,
    this.skipAuth = false,
    super.key,
  });

  final bool skipPersistence;
  final bool skipAuth;

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'ExamVerify',
      theme: ThemeData(
        useMaterial3: true,
        brightness: Brightness.dark,
        scaffoldBackgroundColor: AppColors.background,
        colorScheme: ColorScheme.fromSeed(
          seedColor: AppColors.cyan,
          brightness: Brightness.dark,
          surface: AppColors.panel,
        ),
        fontFamily: 'Segoe UI',
        inputDecorationTheme: InputDecorationTheme(
          filled: true,
          fillColor: AppColors.panelWeak,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: AppColors.border),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: AppColors.border),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(10),
            borderSide: const BorderSide(color: AppColors.cyan),
          ),
        ),
      ),
      home: ExamVerifyShell(
        skipPersistence: skipPersistence,
        skipAuth: skipAuth,
      ),
    );
  }
}

class ExamVerifyShell extends StatefulWidget {
  const ExamVerifyShell({
    this.skipPersistence = false,
    this.skipAuth = false,
    super.key,
  });

  final bool skipPersistence;
  final bool skipAuth;

  @override
  State<ExamVerifyShell> createState() => _ExamVerifyShellState();
}

class _ExamVerifyShellState extends State<ExamVerifyShell> {
  final ExamVerifyStore store = ExamVerifyStore();
  int selectedIndex = 0;
  List<StudentRecord> students = const [];
  List<VerificationRecord> logs = const [];
  List<ExamSessionRecord> examSessions = const [];
  List<ExamEligibilityRecord> examEligibilities = const [];
  bool loading = true;
  AuthUser? authUser;
  DateTime? lastActivity;
  String? authMessage;
  Timer? sessionTimer;

  static const sessionTimeout = Duration(minutes: 10);

  static const List<NavItem> allNavItems = [
    NavItem(Icons.dashboard_outlined, 'Dashboard'),
    NavItem(
      Icons.person_add_alt_1_outlined,
      'Register',
      roles: {'Super Admin', 'Admin'},
    ),
    NavItem(
      Icons.verified_user_outlined,
      'Verify',
      roles: {'Super Admin', 'Admin', 'Invigilator'},
    ),
    NavItem(
      Icons.center_focus_strong_outlined,
      'Auto Identify',
      roles: {'Super Admin', 'Admin', 'Invigilator'},
    ),
    NavItem(
      Icons.groups_2_outlined,
      'Students',
      roles: {'Super Admin', 'Admin'},
    ),
    NavItem(
      Icons.event_available_outlined,
      'Exam Sessions',
      roles: {'Super Admin', 'Admin'},
    ),
    NavItem(
      Icons.analytics_outlined,
      'Evaluation',
      roles: {'Super Admin', 'Admin', 'Viewer'},
    ),
    NavItem(
      Icons.manage_accounts_outlined,
      'Access Requests',
      roles: {'Super Admin'},
    ),
    NavItem(Icons.receipt_long_outlined, 'Logs'),
  ];

  List<NavItem> get navItems {
    final role = authUser?.role ?? 'Viewer';
    return allNavItems.where((item) => item.roles.contains(role)).toList();
  }

  OnlineBackendClient? get onlineClient {
    final user = authUser;
    if (user == null || !user.isOnline) return null;
    return OnlineBackendClient(baseUrl: user.backendUrl!, token: user.token!);
  }

  @override
  void initState() {
    super.initState();
    if (widget.skipAuth) {
      authUser = AuthUser.admin();
      lastActivity = DateTime.now();
    }
    _startSessionTimer();
    _loadData();
  }

  @override
  void dispose() {
    sessionTimer?.cancel();
    super.dispose();
  }

  void _startSessionTimer() {
    sessionTimer = Timer.periodic(const Duration(seconds: 30), (_) {
      if (!mounted ||
          widget.skipAuth ||
          authUser == null ||
          lastActivity == null) {
        return;
      }
      if (DateTime.now().difference(lastActivity!) > sessionTimeout) {
        TrustedSessionCache.clear();
        setState(() {
          authUser = null;
          selectedIndex = 0;
          authMessage = 'Your session expired. Please sign in again.';
        });
      }
    });
  }

  void _touchSession() {
    if (!widget.skipAuth) {
      lastActivity = DateTime.now();
    }
  }

  void _handleLogin(AuthUser user) {
    setState(() {
      authUser = user;
      lastActivity = DateTime.now();
      authMessage = null;
      selectedIndex = 0;
      loading = true;
    });
    _loadData();
  }

  void _logout() {
    TrustedSessionCache.clear();
    setState(() {
      authUser = null;
      lastActivity = null;
      selectedIndex = 0;
      authMessage = null;
    });
  }

  Future<void> _loadData() async {
    List<StudentRecord> loadedStudents = const [];
    List<VerificationRecord> loadedLogs = const [];
    List<ExamSessionRecord> loadedSessions = const [];
    List<ExamEligibilityRecord> loadedEligibilities = const [];
    if (!widget.skipPersistence) {
      try {
        final client = onlineClient;
        if (client != null) {
          final localStudents = await store.listStudents();
          final deletedStudentHashes = await store.listDeletedStudentHashes();
          if (authUser?.isAdmin ?? false) {
            for (final hash in deletedStudentHashes) {
              try {
                await client.deleteStudentHash(hash);
                await store.clearStudentDeletion(hash);
              } catch (_) {
                // Keep the local tombstone until the cloud accepts deletion.
              }
            }
          }
          var remoteStudents = (await client.listStudents())
              .where(
                (student) => !deletedStudentHashes.contains(
                  student.studentNumberHash ??
                      AuthService.hashIdentifier(student.studentNumber),
                ),
              )
              .toList();
          loadedStudents = _mergeRemoteWithLocalCache(
            localStudents,
            remoteStudents,
          );
          await store.replaceStudents(loadedStudents);
          loadedLogs = await client.listLogs();
          loadedSessions = await client.listExamSessions();
          await store.replaceExamSessions(loadedSessions);
          for (final session in loadedSessions) {
            final rows = await client.listExamEligibilities(session.id);
            loadedEligibilities.addAll(rows);
          }
          await store.replaceExamEligibilities(loadedEligibilities);
        } else {
          loadedStudents = await store.listStudents();
          loadedLogs = await store.listLogs();
          loadedSessions = await store.listExamSessions();
          loadedEligibilities = await store.listExamEligibilities();
        }
      } catch (_) {
        // Widget tests run without the Android sqflite plugin. The real app uses
        // the on-device database; tests can still render the dashboard shell.
      }
    }
    loadedLogs = _hydrateVerificationLogs(loadedLogs, loadedStudents);
    if (!mounted) return;
    setState(() {
      students = loadedStudents;
      logs = loadedLogs;
      examSessions = loadedSessions;
      examEligibilities = loadedEligibilities;
      loading = false;
    });
  }

  List<StudentRecord> _mergeRemoteWithLocalCache(
    List<StudentRecord> localStudents,
    List<StudentRecord> remoteStudents,
  ) {
    final localByKey = {
      for (final student in localStudents)
        student.studentNumberHash ??
                AuthService.hashIdentifier(student.studentNumber):
            student,
    };
    final result =
        [
          for (final remote in remoteStudents)
            _mergeStudentCache(
              remote,
              localByKey[remote.studentNumberHash ??
                  AuthService.hashIdentifier(remote.studentNumber)],
            ),
        ]..sort(
          (a, b) =>
              a.fullName.toLowerCase().compareTo(b.fullName.toLowerCase()),
        );
    return result;
  }

  StudentRecord _mergeStudentCache(StudentRecord remote, StudentRecord? local) {
    if (local == null) return remote;
    final localPhotoUsable =
        local.photoPath.isNotEmpty && File(local.photoPath).existsSync();
    return StudentRecord(
      id: remote.id ?? local.id,
      studentNumber: local.studentNumber,
      studentNumberHash:
          remote.studentNumberHash ??
          local.studentNumberHash ??
          AuthService.hashIdentifier(local.studentNumber),
      fullName: remote.fullName,
      program: remote.program,
      level: remote.level,
      status: remote.status,
      eligible: remote.eligible,
      note: remote.note.isNotEmpty ? remote.note : local.note,
      photoPath: localPhotoUsable ? local.photoPath : remote.photoPath,
      signature: remote.signature.isNotEmpty
          ? remote.signature
          : local.signature,
      backendEmbedding: remote.backendEmbedding ?? local.backendEmbedding,
      backendName: remote.backendName ?? local.backendName,
    );
  }

  List<VerificationRecord> _hydrateVerificationLogs(
    List<VerificationRecord> sourceLogs,
    List<StudentRecord> sourceStudents,
  ) {
    final studentsByHash = {
      for (final student in sourceStudents)
        student.studentNumberHash ??
                AuthService.hashIdentifier(student.studentNumber):
            student,
    };
    return [
      for (final log in sourceLogs)
        log.withStudentContext(
          studentsByHash[log.studentNumberHash ??
              AuthService.hashIdentifier(log.studentNumber)],
        ),
    ];
  }

  Future<void> _resetEvaluationMetrics() async {
    _touchSession();
    final client = onlineClient;
    if (client != null) {
      await client.clearVerificationLogs();
    } else {
      await store.clearLogs();
    }
    await _loadData();
  }

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(
        body: Center(child: CircularProgressIndicator(color: AppColors.cyan)),
      );
    }

    if (authUser == null) {
      return LoginPage(message: authMessage, onLogin: _handleLogin);
    }

    return LayoutBuilder(
      builder: (context, constraints) {
        final isDesktop = constraints.maxWidth >= 940;
        final availableItems = navItems;
        final safeIndex = selectedIndex >= availableItems.length
            ? 0
            : selectedIndex;
        final body = _pageForItem(availableItems[safeIndex]);

        return Scaffold(
          body: Container(
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  AppColors.background,
                  Color(0xFF06111F),
                  Color(0xFF071326),
                ],
              ),
            ),
            child: SafeArea(
              child: isDesktop
                  ? Row(
                      children: [
                        SideNavigation(
                          navItems: availableItems,
                          selectedIndex: safeIndex,
                          user: authUser!,
                          onLogout: _logout,
                          onSelected: (index) => setState(() {
                            _touchSession();
                            selectedIndex = index;
                          }),
                        ),
                        Expanded(child: body),
                      ],
                    )
                  : Column(
                      children: [
                        MobileHeader(
                          navItems: availableItems,
                          selectedIndex: safeIndex,
                          user: authUser!,
                          onLogout: _logout,
                          onSelected: (index) => setState(() {
                            _touchSession();
                            selectedIndex = index;
                          }),
                        ),
                        Expanded(child: body),
                      ],
                    ),
            ),
          ),
        );
      },
    );
  }

  Widget _pageForItem(NavItem item) {
    return switch (item.label) {
      'Dashboard' => DashboardPage(students: students, logs: logs),
      'Register' => RegisterPage(
        onStudentRegistered: _registerStudent,
        onlineMode: onlineClient != null,
      ),
      'Verify' => VerifyPage(
        students: students,
        examSessions: examSessions,
        examEligibilities: examEligibilities,
        onVerificationSaved: _saveVerificationInPlace,
        onlineClient: onlineClient,
      ),
      'Auto Identify' => AutoIdentifyPage(
        students: students,
        examSessions: examSessions,
        examEligibilities: examEligibilities,
        onVerificationSaved: _saveVerificationInPlace,
        onlineClient: onlineClient,
      ),
      'Students' => StudentsPage(
        students: students,
        onToggleEligibility: _toggleEligibility,
        onDeleteStudent: _deleteStudent,
      ),
      'Exam Sessions' => ExamSessionsPage(
        students: students,
        sessions: examSessions,
        client: onlineClient,
        onChanged: _loadData,
      ),
      'Evaluation' => EvaluationPage(
        logs: logs,
        onResetMetrics: _resetEvaluationMetrics,
        onlineMode: onlineClient != null,
      ),
      'Access Requests' => AdminRequestsPage(client: onlineClient),
      _ => LogsPage(logs: logs),
    };
  }

  void _selectPage(String label) {
    final index = navItems.indexWhere((item) => item.label == label);
    if (index >= 0) {
      selectedIndex = index;
    }
  }

  Future<void> _registerStudent(StudentRecord student) async {
    _touchSession();
    final client = onlineClient;
    await store.clearStudentDeletion(
      student.studentNumberHash ??
          AuthService.hashIdentifier(student.studentNumber),
    );
    await store.upsertStudent(student);
    if (client != null) {
      await client.registerStudent(student);
    }
    final localStudents = await store.listStudents();
    final loadedStudents = client != null
        ? _mergeRemoteWithLocalCache(localStudents, await client.listStudents())
        : localStudents;
    if (client != null) await store.replaceStudents(loadedStudents);
    if (!mounted) return;
    setState(() {
      students = loadedStudents;
      _selectPage('Students');
    });
  }

  Future<void> _saveVerificationInPlace(VerificationRecord record) =>
      _saveVerificationRecord(record, navigateToLogs: false);

  Future<void> _saveVerificationRecord(
    VerificationRecord record, {
    required bool navigateToLogs,
  }) async {
    _touchSession();
    final client = onlineClient;
    if (client != null) {
      await client.recordVerification(record);
    } else {
      await store.addLog(record);
    }
    final loadedLogs = client != null
        ? _hydrateVerificationLogs(await client.listLogs(), students)
        : _hydrateVerificationLogs(await store.listLogs(), students);
    if (!mounted) return;
    setState(() {
      logs = loadedLogs;
      if (navigateToLogs) _selectPage('Logs');
    });
  }

  Future<void> _toggleEligibility(StudentRecord student) async {
    _touchSession();
    final updated = student.copyWith(eligible: !student.eligible);
    await store.upsertStudent(updated);
    final client = onlineClient;
    if (client != null) {
      await client.registerStudent(updated);
    }
    final localStudents = await store.listStudents();
    final loadedStudents = client != null
        ? _mergeRemoteWithLocalCache(localStudents, await client.listStudents())
        : localStudents;
    if (client != null) await store.replaceStudents(loadedStudents);
    if (!mounted) return;
    setState(() => students = loadedStudents);
  }

  Future<void> _deleteStudent(StudentRecord student) async {
    _touchSession();
    await store.deleteStudent(student);
    final client = onlineClient;
    if (client != null) {
      try {
        await client.deleteStudent(student);
        await store.clearStudentDeletion(
          student.studentNumberHash ??
              AuthService.hashIdentifier(student.studentNumber),
        );
      } catch (_) {
        // The local tombstone prevents reappearing records until cloud sync succeeds.
      }
    }
    final loadedStudents = await store.listStudents();
    if (!mounted) return;
    setState(() => students = loadedStudents);
  }
}

class AuthUser {
  const AuthUser({
    required this.username,
    required this.fullName,
    required this.role,
    this.token,
    this.backendUrl,
  });

  final String username;
  final String fullName;
  final String role;
  final String? token;
  final String? backendUrl;

  bool get isAdmin => role == 'Admin' || role == 'Super Admin';
  bool get isOnline => token != null && backendUrl != null;

  static AuthUser admin() {
    return const AuthUser(
      username: 'admin',
      fullName: 'System Administrator',
      role: 'Super Admin',
    );
  }
}

class TrustedSessionCache {
  static AuthUser? _user;
  static String? _username;
  static String? _backendUrl;
  static DateTime? _expiresAt;

  static AuthUser? get(String username, String backendUrl) {
    final expiresAt = _expiresAt;
    if (expiresAt == null || DateTime.now().isAfter(expiresAt)) {
      clear();
      return null;
    }
    if (_username == username.trim().toLowerCase() &&
        _backendUrl == backendUrl.trim()) {
      return _user;
    }
    return null;
  }

  static void store(AuthUser user, String backendUrl) {
    _user = user;
    _username = user.username.trim().toLowerCase();
    _backendUrl = backendUrl.trim();
    _expiresAt = DateTime.now().add(const Duration(hours: 4));
  }

  static void clear() {
    _user = null;
    _username = null;
    _backendUrl = null;
    _expiresAt = null;
  }
}

class AuthService {
  static const _identifierPepper = 'ExamVerify-Local-Identifier-Pepper-v2';

  static const _users = {
    'admin': AuthUser(
      username: 'admin',
      fullName: 'System Administrator',
      role: 'Super Admin',
    ),
    'invigilator': AuthUser(
      username: 'invigilator',
      fullName: 'Exam Invigilator',
      role: 'Invigilator',
    ),
    'viewer': AuthUser(
      username: 'viewer',
      fullName: 'Audit Viewer',
      role: 'Viewer',
    ),
  };

  static const _passwords = {
    'admin': 'Admin@12345',
    'invigilator': 'Verify@12345',
    'viewer': 'View@12345',
  };

  static const _totpSecrets = {
    'admin': 'JBSWY3DPEHPK3PXP',
    'invigilator': 'JBSWY3DPEHPK3PXQ',
    'viewer': 'JBSWY3DPEHPK3PXR',
  };

  static AuthUser? authenticate(
    String username,
    String password,
    String otpCode,
  ) {
    final normalized = username.trim().toLowerCase();
    if (_passwords[normalized] != password) return null;
    final secret = _totpSecrets[normalized];
    if (secret == null || !verifyTotp(secret, otpCode)) return null;
    return _users[normalized];
  }

  static String? setupSecret(String username) {
    return _totpSecrets[username.trim().toLowerCase()];
  }

  static String? currentCode(String username) {
    final secret = setupSecret(username);
    if (secret == null) return null;
    return generateTotp(secret);
  }

  static String hashIdentifier(String studentNumber) {
    final normalized = studentNumber.trim().toUpperCase();
    return sha256
        .convert(utf8.encode('$_identifierPepper|$normalized'))
        .toString();
  }

  static String maskIdentifier(String studentNumber) {
    final cleaned = studentNumber.trim();
    if (cleaned.length <= 4) return '*' * cleaned.length;
    return '${cleaned.substring(0, 2)}${'*' * math.max(2, cleaned.length - 4)}${cleaned.substring(cleaned.length - 2)}';
  }

  static String generateTotp(String secret, {DateTime? at}) {
    final seconds = ((at ?? DateTime.now()).millisecondsSinceEpoch ~/ 1000);
    final counter = seconds ~/ 30;
    final counterBytes = ByteData(8)..setUint64(0, counter);
    final key = _base32Decode(secret);
    final digest = Hmac(
      sha1,
      key,
    ).convert(counterBytes.buffer.asUint8List()).bytes;
    final offset = digest.last & 0x0f;
    final binary =
        ((digest[offset] & 0x7f) << 24) |
        ((digest[offset + 1] & 0xff) << 16) |
        ((digest[offset + 2] & 0xff) << 8) |
        (digest[offset + 3] & 0xff);
    return (binary % 1000000).toString().padLeft(6, '0');
  }

  static bool verifyTotp(String secret, String otpCode) {
    final cleaned = otpCode.replaceAll(RegExp(r'[^0-9]'), '');
    if (cleaned.length != 6) return false;
    final now = DateTime.now();
    for (final step in [-1, 0, 1]) {
      final expected = generateTotp(
        secret,
        at: now.add(Duration(seconds: 30 * step)),
      );
      if (expected == cleaned) return true;
    }
    return false;
  }

  static List<int> _base32Decode(String input) {
    const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
    var buffer = 0;
    var bitsLeft = 0;
    final output = <int>[];
    for (final codeUnit in input.toUpperCase().codeUnits) {
      final char = String.fromCharCode(codeUnit);
      if (char == '=') break;
      final value = alphabet.indexOf(char);
      if (value < 0) continue;
      buffer = (buffer << 5) | value;
      bitsLeft += 5;
      if (bitsLeft >= 8) {
        output.add((buffer >> (bitsLeft - 8)) & 0xff);
        bitsLeft -= 8;
      }
    }
    return Uint8List.fromList(output);
  }
}

class AppPanel extends StatelessWidget {
  const AppPanel({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(22),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.border),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.28),
            blurRadius: 28,
            offset: const Offset(0, 18),
          ),
        ],
      ),
      child: child,
    );
  }
}

class InfoBanner extends StatelessWidget {
  const InfoBanner({required this.message, required this.color, super.key});

  final String message;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: color.withValues(alpha: 0.34)),
      ),
      child: Text(
        message,
        style: TextStyle(color: color, fontWeight: FontWeight.w700),
      ),
    );
  }
}

class LoginPage extends StatefulWidget {
  const LoginPage({required this.onLogin, this.message, super.key});

  final ValueChanged<AuthUser> onLogin;
  final String? message;

  @override
  State<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends State<LoginPage>
    with SingleTickerProviderStateMixin {
  final usernameController = TextEditingController();
  final passwordController = TextEditingController();
  final backendUrlController = TextEditingController(
    text: AppConfig.cloudApiUrl,
  );
  String? error;
  String? statusMessage;
  String? pendingOnlineUsername;
  String? pendingDemoCode;
  String selectedRole = 'Admin';
  bool onlineMode = true;
  bool busy = false;
  bool passwordVisible = false;
  late final AnimationController _motionController;

  bool get _hasCredentials =>
      usernameController.text.trim().isNotEmpty &&
      passwordController.text.isNotEmpty;

  @override
  void initState() {
    super.initState();
    _motionController = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 7),
    )..repeat();
    usernameController.addListener(_refreshCredentials);
    passwordController.addListener(_refreshCredentials);
  }

  @override
  void dispose() {
    _motionController.dispose();
    usernameController.removeListener(_refreshCredentials);
    passwordController.removeListener(_refreshCredentials);
    usernameController.dispose();
    passwordController.dispose();
    backendUrlController.dispose();
    super.dispose();
  }

  void _refreshCredentials() {
    if (mounted) setState(() {});
  }

  Future<void> _submitCredentials() async {
    if (!_hasCredentials) {
      setState(() {
        error = 'Enter your credentials to continue.';
        statusMessage = null;
      });
      return;
    }
    if (onlineMode) {
      await _requestOnlineOtp(openDialog: true);
      return;
    }
    await _showOtpExperience();
  }

  Future<void> _requestOnlineOtp({required bool openDialog}) async {
    setState(() {
      busy = true;
      error = null;
      statusMessage = 'Preparing identity challenge...';
    });
    try {
      final client = OnlineBackendClient(baseUrl: backendUrlController.text);
      final response = await client.requestOtp(
        usernameController.text,
        passwordController.text,
        requestedRole: selectedRole,
      );
      if (!mounted) return;
      setState(() {
        pendingOnlineUsername = usernameController.text.trim().toLowerCase();
        pendingDemoCode =
            response['developer_code'] as String? ??
            response['demo_code'] as String?;
        statusMessage = 'Verification code sent.';
      });
      if (openDialog) await _showOtpExperience();
    } catch (err) {
      setState(() {
        error = _friendlyLoginError(err);
        statusMessage = null;
      });
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String _friendlyLoginError(Object error) {
    final message = error.toString().replaceFirst('Exception: ', '').trim();
    final lower = message.toLowerCase();
    if (message.isEmpty ||
        lower.contains('string_too_short') ||
        lower.contains('invalid credentials') ||
        lower.contains('password') ||
        lower.contains('username') ||
        lower.contains('email') ||
        lower.contains('unauthorized')) {
      return 'Wrong email/username or password. Please check your details and try again.';
    }
    if (lower.contains('locked')) {
      return 'This account is temporarily locked. Please wait a few minutes or contact the administrator.';
    }
    if (lower.contains('under review') || lower.contains('not approved')) {
      return message;
    }
    return 'Sign-in could not be completed. Please check your details and try again.';
  }

  Future<void> _showOtpExperience() async {
    final result = await Navigator.of(context).push<bool>(
      MaterialPageRoute<bool>(
        fullscreenDialog: true,
        builder: (context) => _OtpVerificationDialog(
          onlineMode: onlineMode,
          demoCode: pendingDemoCode,
          onVerify: _verifyOtp,
          onResend: onlineMode
              ? () => _requestOnlineOtp(openDialog: false)
              : null,
        ),
      ),
    );
    if (!mounted) return;
    if (result != true) {
      setState(() {
        statusMessage = null;
        pendingOnlineUsername = null;
        pendingDemoCode = null;
      });
    }
  }

  Future<void> _verifyOtp(String code) async {
    if (onlineMode) {
      final client = OnlineBackendClient(baseUrl: backendUrlController.text);
      final user = await client.verifyOtp(
        pendingOnlineUsername ?? usernameController.text.trim().toLowerCase(),
        code,
      );
      if (!_roleAllows(user)) {
        throw Exception('This account is not approved for the selected role.');
      }
      widget.onLogin(user);
      return;
    }
    final user = AuthService.authenticate(
      usernameController.text,
      passwordController.text,
      code,
    );
    if (user == null) {
      throw Exception('Identity code was not accepted.');
    }
    if (!_roleAllows(user)) {
      throw Exception('This account is not approved for the selected role.');
    }
    widget.onLogin(user);
  }

  bool _roleAllows(AuthUser user) {
    if (selectedRole == 'Admin') return user.isAdmin;
    return user.role == selectedRole;
  }

  Future<void> _openDeveloperSettings() async {
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (context) => _DeveloperSettingsSheet(
        onlineMode: onlineMode,
        backendUrlController: backendUrlController,
        usernameController: usernameController,
        demoCode: pendingDemoCode,
        onModeChanged: pendingOnlineUsername == null
            ? (value) => setState(() {
                onlineMode = value;
                pendingOnlineUsername = null;
                pendingDemoCode = null;
                error = null;
                statusMessage = null;
              })
            : null,
      ),
    );
  }

  Future<void> _showAccessRequest(String role) async {
    await showDialog<void>(
      context: context,
      barrierDismissible: true,
      builder: (context) => _AccessRequestDialog(
        initialRole: role,
        onSubmit: (request) async {
          final client = OnlineBackendClient(
            baseUrl: backendUrlController.text,
          );
          await client.submitAccessRequest(request);
        },
      ),
    );
  }

  void _showPasswordHelp() {
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        content: Text(
          'Contact the Super Administrator to restore account access.',
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final size = MediaQuery.sizeOf(context);
    final isDesktop = size.width >= 900;

    return Scaffold(
      body: AnimatedBuilder(
        animation: _motionController,
        builder: (context, _) {
          final loginPanel = _LoginGlassPanel(
            usernameController: usernameController,
            passwordController: passwordController,
            busy: busy,
            enabled: pendingOnlineUsername == null,
            canSubmit: _hasCredentials,
            error: error,
            statusMessage: statusMessage,
            sessionMessage: widget.message,
            progress: _motionController.value,
            onSubmit: _submitCredentials,
            onDeveloperOpen: _openDeveloperSettings,
            selectedRole: selectedRole,
            onRoleChanged: (role) => setState(() => selectedRole = role),
            passwordVisible: passwordVisible,
            onPasswordVisibilityChanged: () =>
                setState(() => passwordVisible = !passwordVisible),
            onForgotPassword: _showPasswordHelp,
            onInvigilatorSignup: () => _showAccessRequest('Invigilator'),
            onAdminRequest: () => _showAccessRequest('Admin'),
          );

          return Stack(
            children: [
              const _CinematicLoginBackground(),
              if (isDesktop)
                CustomPaint(
                  painter: _ParticleFieldPainter(_motionController.value),
                  size: Size.infinite,
                ),
              SafeArea(
                child: isDesktop
                    ? Padding(
                        padding: const EdgeInsets.all(28),
                        child: Row(
                          children: [
                            Expanded(
                              flex: 6,
                              child: _CinematicBrandPanel(
                                progress: _motionController.value,
                                onDeveloperOpen: _openDeveloperSettings,
                              ),
                            ),
                            const SizedBox(width: 30),
                            Expanded(
                              flex: 4,
                              child: Align(
                                alignment: Alignment.center,
                                child: SingleChildScrollView(
                                  padding: const EdgeInsets.symmetric(
                                    vertical: 12,
                                  ),
                                  child: ConstrainedBox(
                                    constraints: const BoxConstraints(
                                      maxWidth: 470,
                                    ),
                                    child: loginPanel,
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                      )
                    : LayoutBuilder(
                        builder: (context, constraints) {
                          return SingleChildScrollView(
                            keyboardDismissBehavior:
                                ScrollViewKeyboardDismissBehavior.onDrag,
                            padding: const EdgeInsets.fromLTRB(20, 18, 20, 22),
                            child: ConstrainedBox(
                              constraints: BoxConstraints(
                                minHeight: math.max(
                                  0,
                                  constraints.maxHeight - 40,
                                ),
                              ),
                              child: Center(
                                child: ConstrainedBox(
                                  constraints: const BoxConstraints(
                                    maxWidth: 470,
                                  ),
                                  child: loginPanel,
                                ),
                              ),
                            ),
                          );
                        },
                      ),
              ),
            ],
          );
        },
      ),
    );
  }
}

class _CinematicLoginBackground extends StatelessWidget {
  const _CinematicLoginBackground();

  @override
  Widget build(BuildContext context) {
    return Container(
      decoration: const BoxDecoration(
        gradient: RadialGradient(
          center: Alignment(-0.55, -0.28),
          radius: 1.08,
          colors: [Color(0xFF0A2C43), Color(0xFF061426), AppColors.background],
        ),
      ),
      child: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topRight,
            end: Alignment.bottomLeft,
            colors: [Color(0x6622D3EE), Color(0x00050B18), Color(0xAA020814)],
          ),
        ),
      ),
    );
  }
}

class _CinematicBrandPanel extends StatelessWidget {
  const _CinematicBrandPanel({
    required this.progress,
    required this.onDeveloperOpen,
  });

  final double progress;
  final VoidCallback onDeveloperOpen;

  @override
  Widget build(BuildContext context) {
    final headingStyle = Theme.of(context).textTheme.displaySmall?.copyWith(
      color: Colors.white,
      fontWeight: FontWeight.w900,
      height: 0.95,
      letterSpacing: 0,
    );

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(34),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          GestureDetector(
            onLongPress: onDeveloperOpen,
            child: const Row(
              mainAxisSize: MainAxisSize.min,
              children: [BrandMark(), SizedBox(width: 14), BrandText()],
            ),
          ),
          Expanded(
            child: Center(
              child: _BiometricVisual(progress: progress, compact: false),
            ),
          ),
          Text('Secure Exam Console', style: headingStyle),
          const SizedBox(height: 14),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 560),
            child: const Text(
              'Biometric access control for high-stakes academic verification.',
              style: TextStyle(
                color: AppColors.soft,
                fontSize: 17,
                height: 1.45,
                fontWeight: FontWeight.w500,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _LoginGlassPanel extends StatelessWidget {
  const _LoginGlassPanel({
    required this.usernameController,
    required this.passwordController,
    required this.busy,
    required this.enabled,
    required this.canSubmit,
    required this.statusMessage,
    required this.progress,
    required this.onSubmit,
    required this.onDeveloperOpen,
    required this.selectedRole,
    required this.onRoleChanged,
    required this.passwordVisible,
    required this.onPasswordVisibilityChanged,
    required this.onForgotPassword,
    required this.onInvigilatorSignup,
    required this.onAdminRequest,
    this.error,
    this.sessionMessage,
  });

  final TextEditingController usernameController;
  final TextEditingController passwordController;
  final bool busy;
  final bool enabled;
  final bool canSubmit;
  final String? statusMessage;
  final String? error;
  final String? sessionMessage;
  final double progress;
  final VoidCallback onSubmit;
  final VoidCallback onDeveloperOpen;
  final String selectedRole;
  final ValueChanged<String> onRoleChanged;
  final bool passwordVisible;
  final VoidCallback onPasswordVisibilityChanged;
  final VoidCallback onForgotPassword;
  final VoidCallback onInvigilatorSignup;
  final VoidCallback onAdminRequest;

  @override
  Widget build(BuildContext context) {
    return _GlassSurface(
      padding: const EdgeInsets.fromLTRB(28, 28, 28, 24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          GestureDetector(
            onLongPress: onDeveloperOpen,
            child: Row(
              children: [
                const BrandMark(),
                const SizedBox(width: 14),
                const Expanded(child: BrandText()),
                _NetworkPulse(progress: progress),
              ],
            ),
          ),
          const SizedBox(height: 28),
          Text(
            'Sign in',
            style: Theme.of(context).textTheme.headlineMedium?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.w900,
              letterSpacing: 0,
            ),
          ),
          const SizedBox(height: 8),
          const Text(
            'Select your role and continue securely.',
            style: TextStyle(color: AppColors.muted, height: 1.45),
          ),
          const SizedBox(height: 22),
          _RoleSelector(
            role: selectedRole,
            enabled: enabled && !busy,
            onChanged: onRoleChanged,
          ),
          if (statusMessage != null) ...[
            const SizedBox(height: 16),
            _StatusPill(message: statusMessage!, color: AppColors.green),
          ],
          if (sessionMessage != null) ...[
            const SizedBox(height: 14),
            InfoBanner(message: sessionMessage!, color: AppColors.amber),
          ],
          if (error != null) ...[
            const SizedBox(height: 14),
            InfoBanner(message: error!, color: AppColors.red),
          ],
          const SizedBox(height: 20),
          _PremiumTextField(
            controller: usernameController,
            label: 'Email or Username',
            icon: Icons.person_outline,
            enabled: enabled && !busy,
            textInputAction: TextInputAction.next,
          ),
          const SizedBox(height: 14),
          _PremiumTextField(
            controller: passwordController,
            label: 'Password',
            icon: Icons.lock_outline,
            enabled: enabled && !busy,
            obscureText: !passwordVisible,
            suffixIcon: IconButton(
              tooltip: passwordVisible ? 'Hide password' : 'Show password',
              onPressed: busy ? null : onPasswordVisibilityChanged,
              icon: Icon(
                passwordVisible
                    ? Icons.visibility_off_outlined
                    : Icons.visibility_outlined,
                color: AppColors.soft,
              ),
            ),
            onSubmitted: (_) => onSubmit(),
          ),
          Align(
            alignment: Alignment.centerRight,
            child: TextButton(
              onPressed: busy ? null : onForgotPassword,
              child: const Text('Forgot Password?'),
            ),
          ),
          CheckboxListTile(
            value: true,
            dense: true,
            visualDensity: VisualDensity.compact,
            contentPadding: EdgeInsets.zero,
            activeColor: AppColors.cyan,
            checkboxShape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(5),
            ),
            title: const Text(
              'Password and OTP required for every sign-in',
              style: TextStyle(color: AppColors.soft, fontSize: 13),
            ),
            onChanged: null,
          ),
          const SizedBox(height: 24),
          _PremiumActionButton(
            label: busy ? 'Signing in...' : 'Sign in',
            busy: busy,
            enabled: canSubmit && !busy,
            onPressed: onSubmit,
          ),
          const SizedBox(height: 16),
          Wrap(
            alignment: WrapAlignment.center,
            runSpacing: 2,
            children: [
              const Text(
                'Become Invigilator?',
                style: TextStyle(color: AppColors.muted, fontSize: 13),
              ),
              TextButton(
                onPressed: busy ? null : onInvigilatorSignup,
                child: const Text('Sign up'),
              ),
            ],
          ),
          Center(
            child: TextButton(
              onPressed: busy ? null : onAdminRequest,
              child: const Text('Request Admin Access'),
            ),
          ),
        ],
      ),
    );
  }
}

class _RoleSelector extends StatelessWidget {
  const _RoleSelector({
    required this.role,
    required this.enabled,
    required this.onChanged,
  });

  final String role;
  final bool enabled;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(5),
      decoration: BoxDecoration(
        color: Colors.white.withValues(alpha: 0.035),
        borderRadius: BorderRadius.circular(15),
        border: Border.all(color: AppColors.border),
      ),
      child: Row(
        children: [
          _RoleOption(
            label: 'Admin',
            selected: role == 'Admin',
            enabled: enabled,
            onTap: () => onChanged('Admin'),
          ),
          const SizedBox(width: 5),
          _RoleOption(
            label: 'Invigilator',
            selected: role == 'Invigilator',
            enabled: enabled,
            onTap: () => onChanged('Invigilator'),
          ),
        ],
      ),
    );
  }
}

class _RoleOption extends StatelessWidget {
  const _RoleOption({
    required this.label,
    required this.selected,
    required this.enabled,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: InkWell(
        onTap: enabled ? onTap : null,
        borderRadius: BorderRadius.circular(11),
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 180),
          padding: const EdgeInsets.symmetric(vertical: 12),
          decoration: BoxDecoration(
            color: selected
                ? AppColors.cyan.withValues(alpha: 0.14)
                : Colors.transparent,
            borderRadius: BorderRadius.circular(11),
            border: Border.all(
              color: selected
                  ? AppColors.cyan.withValues(alpha: 0.42)
                  : Colors.transparent,
            ),
          ),
          alignment: Alignment.center,
          child: Text(
            'Sign in as $label',
            style: TextStyle(
              fontSize: 13,
              fontWeight: selected ? FontWeight.w800 : FontWeight.w600,
              color: selected ? Colors.white : AppColors.muted,
            ),
          ),
        ),
      ),
    );
  }
}

class _OtpVerificationDialog extends StatefulWidget {
  const _OtpVerificationDialog({
    required this.onlineMode,
    required this.onVerify,
    this.onResend,
    this.demoCode,
  });

  final bool onlineMode;
  final String? demoCode;
  final Future<void> Function(String code) onVerify;
  final Future<void> Function()? onResend;

  @override
  State<_OtpVerificationDialog> createState() => _OtpVerificationDialogState();
}

class _OtpVerificationDialogState extends State<_OtpVerificationDialog> {
  final otpController = TextEditingController();
  final secondsRemaining = ValueNotifier<int>(60);
  Timer? timer;
  bool verifying = false;
  bool success = false;
  String? error;
  bool autoSubmitted = false;

  @override
  void initState() {
    super.initState();
    otpController.addListener(_handleOtpChanged);
    timer = Timer.periodic(const Duration(seconds: 1), (timer) {
      if (!mounted) return;
      if (secondsRemaining.value <= 0) {
        timer.cancel();
      } else {
        secondsRemaining.value -= 1;
      }
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    secondsRemaining.dispose();
    otpController.removeListener(_handleOtpChanged);
    otpController.dispose();
    super.dispose();
  }

  void _handleOtpChanged() {
    final digits = otpController.text.trim();
    if (digits.length == 6 && !verifying && !success && !autoSubmitted) {
      autoSubmitted = true;
      Future<void>.delayed(const Duration(milliseconds: 140), () {
        if (mounted) _verify();
      });
    }
    if (digits.length < 6) autoSubmitted = false;
  }

  Future<void> _verify() async {
    if (otpController.text.trim().length < 6) {
      setState(() => error = 'Enter the 6-digit verification code.');
      return;
    }
    setState(() {
      verifying = true;
      error = null;
    });
    try {
      await widget.onVerify(otpController.text.trim());
      if (!mounted) return;
      setState(() => success = true);
      await Future<void>.delayed(const Duration(milliseconds: 520));
      if (mounted) Navigator.of(context).pop(true);
    } catch (err) {
      if (!mounted) return;
      setState(() {
        verifying = false;
        final message = err.toString().replaceFirst('Exception: ', '').trim();
        error = message.isEmpty
            ? 'Verification code was not accepted.'
            : message;
      });
    }
  }

  Future<void> _resend() async {
    if (widget.onResend == null) return;
    setState(() {
      verifying = true;
      error = null;
    });
    try {
      await widget.onResend!();
      if (!mounted) return;
      secondsRemaining.value = 60;
      setState(() {
        verifying = false;
        autoSubmitted = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        verifying = false;
        error = 'Unable to refresh the verification code.';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final viewInsets = MediaQuery.viewInsetsOf(context);
    final screen = MediaQuery.sizeOf(context);
    final keyboardOpen = viewInsets.bottom > 40;
    final availableHeight = math.max(
      250.0,
      screen.height - viewInsets.bottom - 40,
    );
    return Scaffold(
      backgroundColor: AppColors.background,
      body: Stack(
        children: [
          const _CinematicLoginBackground(),
          SafeArea(
            child: Center(
              child: ConstrainedBox(
                constraints: BoxConstraints(
                  maxWidth: 430,
                  maxHeight: availableHeight,
                ),
                child: SingleChildScrollView(
                  keyboardDismissBehavior:
                      ScrollViewKeyboardDismissBehavior.onDrag,
                  padding: EdgeInsets.symmetric(
                    horizontal: screen.width < 480 ? 16 : 22,
                    vertical: 16,
                  ),
                  child: _GlassSurface(
                    padding: EdgeInsets.all(
                      keyboardOpen ? 18 : (screen.width < 390 ? 18 : 26),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      crossAxisAlignment: CrossAxisAlignment.center,
                      children: [
                        if (!keyboardOpen) ...[
                          AnimatedContainer(
                            duration: const Duration(milliseconds: 300),
                            width: 68,
                            height: 68,
                            decoration: BoxDecoration(
                              shape: BoxShape.circle,
                              color:
                                  (success ? AppColors.green : AppColors.cyan)
                                      .withValues(alpha: 0.12),
                              border: Border.all(
                                color: success
                                    ? AppColors.green
                                    : AppColors.cyan,
                              ),
                              boxShadow: [
                                BoxShadow(
                                  color:
                                      (success
                                              ? AppColors.green
                                              : AppColors.cyan)
                                          .withValues(alpha: 0.28),
                                  blurRadius: 28,
                                ),
                              ],
                            ),
                            child: Icon(
                              success
                                  ? Icons.verified_outlined
                                  : Icons.mark_email_read_outlined,
                              color: success ? AppColors.green : AppColors.cyan,
                              size: 32,
                            ),
                          ),
                          const SizedBox(height: 18),
                        ],
                        Text(
                          success
                              ? 'Access Approved'
                              : 'Enter Verification Code',
                          textAlign: TextAlign.center,
                          style: Theme.of(context).textTheme.titleLarge
                              ?.copyWith(
                                color: Colors.white,
                                fontWeight: FontWeight.w900,
                              ),
                        ),
                        if (!keyboardOpen) ...[
                          const SizedBox(height: 8),
                          Text(
                            widget.onlineMode
                                ? 'A secure code has been sent to the authorized account.'
                                : 'Enter the current authenticator code.',
                            textAlign: TextAlign.center,
                            style: const TextStyle(
                              color: AppColors.muted,
                              height: 1.4,
                            ),
                          ),
                        ],
                        SizedBox(height: keyboardOpen ? 14 : 22),
                        SegmentedOtpField(
                          controller: otpController,
                          enabled: !verifying && !success,
                          onSubmitted: (_) => _verify(),
                        ),
                        if (error != null) ...[
                          const SizedBox(height: 14),
                          InfoBanner(message: error!, color: AppColors.red),
                        ],
                        SizedBox(height: keyboardOpen ? 14 : 18),
                        _PremiumActionButton(
                          label: verifying
                              ? 'Checking...'
                              : success
                              ? 'Opening'
                              : 'Verify',
                          busy: verifying && !success,
                          enabled: !success && !verifying,
                          onPressed: _verify,
                        ),
                        SizedBox(height: keyboardOpen ? 8 : 14),
                        Wrap(
                          alignment: WrapAlignment.center,
                          crossAxisAlignment: WrapCrossAlignment.center,
                          spacing: 14,
                          runSpacing: 4,
                          children: [
                            ValueListenableBuilder<int>(
                              valueListenable: secondsRemaining,
                              builder: (context, seconds, _) => Text(
                                seconds > 0
                                    ? 'Code expires in ${seconds}s'
                                    : 'Code ready to refresh',
                                style: const TextStyle(
                                  color: AppColors.muted,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                            if (widget.onResend != null)
                              ValueListenableBuilder<int>(
                                valueListenable: secondsRemaining,
                                builder: (context, seconds, _) => TextButton(
                                  onPressed: seconds > 0 || verifying
                                      ? null
                                      : _resend,
                                  child: const Text('Resend'),
                                ),
                              ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _AccessRequestDialog extends StatefulWidget {
  const _AccessRequestDialog({
    required this.initialRole,
    required this.onSubmit,
  });

  final String initialRole;
  final Future<void> Function(AdminAccessRequestDraft request) onSubmit;

  @override
  State<_AccessRequestDialog> createState() => _AccessRequestDialogState();
}

class _AccessRequestDialogState extends State<_AccessRequestDialog> {
  final formKey = GlobalKey<FormState>();
  final fullNameController = TextEditingController();
  final emailController = TextEditingController();
  final usernameController = TextEditingController();
  final phoneController = TextEditingController();
  final departmentController = TextEditingController();
  final noteController = TextEditingController();
  late String role;
  bool submitting = false;
  bool submitted = false;
  String? message;
  Color messageColor = AppColors.green;

  @override
  void initState() {
    super.initState();
    role = widget.initialRole;
  }

  @override
  void dispose() {
    fullNameController.dispose();
    emailController.dispose();
    usernameController.dispose();
    phoneController.dispose();
    departmentController.dispose();
    noteController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!formKey.currentState!.validate()) return;
    setState(() {
      submitting = true;
      message = null;
    });
    try {
      await widget.onSubmit(
        AdminAccessRequestDraft(
          fullName: fullNameController.text.trim(),
          email: emailController.text.trim(),
          username: usernameController.text.trim(),
          phoneNumber: phoneController.text.trim(),
          department: departmentController.text.trim(),
          requestedRole: role,
          note: noteController.text.trim(),
        ),
      );
      if (!mounted) return;
      setState(() {
        submitted = true;
        message = null;
        messageColor = AppColors.green;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        message = 'The request could not be submitted right now.';
        messageColor = AppColors.red;
      });
    } finally {
      if (mounted) setState(() => submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Dialog(
      insetPadding: const EdgeInsets.all(18),
      backgroundColor: Colors.transparent,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 520),
        child: _GlassSurface(
          padding: const EdgeInsets.all(24),
          child: Form(
            key: formKey,
            child: SingleChildScrollView(
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (submitted) ...[
                    const Icon(
                      Icons.check_circle_outline,
                      color: AppColors.green,
                      size: 46,
                    ),
                    const SizedBox(height: 14),
                    Text(
                      'Application submitted',
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 10),
                    const Text(
                      'Your access request is being reviewed by the Super Administrator. You will be notified once approved.',
                      textAlign: TextAlign.center,
                      style: TextStyle(color: AppColors.muted, height: 1.45),
                    ),
                    const SizedBox(height: 24),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton(
                        onPressed: () => Navigator.of(context).pop(),
                        child: const Text('Done'),
                      ),
                    ),
                  ] else ...[
                    Text(
                      role == 'Admin'
                          ? 'Request Admin Access'
                          : 'Invigilator Sign Up',
                      style: Theme.of(context).textTheme.titleLarge?.copyWith(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 8),
                    const Text(
                      'Submit your details for approval.',
                      style: TextStyle(color: AppColors.muted),
                    ),
                    const SizedBox(height: 18),
                    AppTextField(
                      controller: fullNameController,
                      label: 'Full name',
                    ),
                    const SizedBox(height: 12),
                    AppTextField(controller: emailController, label: 'Email'),
                    const SizedBox(height: 12),
                    AppTextField(
                      controller: usernameController,
                      label: 'Preferred username',
                    ),
                    const SizedBox(height: 12),
                    AppTextField(
                      controller: phoneController,
                      label: 'Phone number (optional)',
                      required: false,
                    ),
                    const SizedBox(height: 12),
                    AppTextField(
                      controller: departmentController,
                      label: 'Department / program (optional)',
                      required: false,
                    ),
                    const SizedBox(height: 12),
                    DropdownButtonFormField<String>(
                      initialValue: role,
                      decoration: const InputDecoration(
                        labelText: 'Requested role',
                      ),
                      items: const [
                        DropdownMenuItem(
                          value: 'Invigilator',
                          child: Text('Invigilator'),
                        ),
                        DropdownMenuItem(value: 'Admin', child: Text('Admin')),
                      ],
                      onChanged: submitting
                          ? null
                          : (value) => setState(() => role = value ?? role),
                    ),
                    const SizedBox(height: 12),
                    AppTextField(
                      controller: noteController,
                      label: 'Request note (optional)',
                      required: false,
                    ),
                    if (message != null) ...[
                      const SizedBox(height: 14),
                      InfoBanner(message: message!, color: messageColor),
                    ],
                    const SizedBox(height: 20),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: submitting
                                ? null
                                : () => Navigator.of(context).pop(),
                            child: const Text('Cancel'),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: FilledButton.icon(
                            onPressed: submitting ? null : _submit,
                            icon: submitting
                                ? const SizedBox(
                                    width: 16,
                                    height: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Icon(Icons.verified_user_outlined),
                            label: Text(
                              submitting ? 'Submitting...' : 'Submit Request',
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _DeveloperSettingsSheet extends StatefulWidget {
  const _DeveloperSettingsSheet({
    required this.onlineMode,
    required this.backendUrlController,
    required this.usernameController,
    required this.onModeChanged,
    this.demoCode,
  });

  final bool onlineMode;
  final TextEditingController backendUrlController;
  final TextEditingController usernameController;
  final ValueChanged<bool>? onModeChanged;
  final String? demoCode;

  @override
  State<_DeveloperSettingsSheet> createState() =>
      _DeveloperSettingsSheetState();
}

class _DeveloperSettingsSheetState extends State<_DeveloperSettingsSheet> {
  bool testing = false;
  String? testResult;

  Future<void> _testConnection() async {
    setState(() {
      testing = true;
      testResult = null;
    });
    try {
      final client = OnlineBackendClient(
        baseUrl: widget.backendUrlController.text,
      );
      await client.healthCheck();
      setState(() => testResult = 'Secure service reachable.');
    } catch (_) {
      setState(() => testResult = 'Secure service unavailable.');
    } finally {
      if (mounted) setState(() => testing = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final secret = AuthService.setupSecret(widget.usernameController.text);
    final code = AuthService.currentCode(widget.usernameController.text);

    return Padding(
      padding: EdgeInsets.only(
        left: 18,
        right: 18,
        bottom: MediaQuery.viewInsetsOf(context).bottom + 18,
      ),
      child: _GlassSurface(
        padding: const EdgeInsets.all(22),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              'Developer Settings',
              style: Theme.of(context).textTheme.titleLarge?.copyWith(
                color: Colors.white,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 6),
            const Text(
              'Production login keeps these controls hidden.',
              style: TextStyle(color: AppColors.muted),
            ),
            const SizedBox(height: 18),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              value: widget.onlineMode,
              activeThumbColor: AppColors.cyan,
              title: const Text('Online platform mode'),
              onChanged: widget.onModeChanged,
            ),
            const SizedBox(height: 10),
            TextField(
              controller: widget.backendUrlController,
              decoration: const InputDecoration(labelText: 'Backend endpoint'),
            ),
            const SizedBox(height: 14),
            Row(
              children: [
                Expanded(
                  child: OutlinedButton.icon(
                    onPressed: testing ? null : _testConnection,
                    icon: testing
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.hub_outlined),
                    label: const Text('Test connection'),
                  ),
                ),
              ],
            ),
            if (testResult != null) ...[
              const SizedBox(height: 12),
              InfoBanner(
                message: testResult!,
                color: testResult!.contains('reachable')
                    ? AppColors.green
                    : AppColors.red,
              ),
            ],
            const SizedBox(height: 14),
            Text(
              [
                if (widget.demoCode != null) 'Fallback OTP: ${widget.demoCode}',
                if (secret != null && code != null)
                  'Local authenticator: $code',
                if (secret != null) 'Secret: $secret',
              ].join('\n'),
              style: const TextStyle(
                color: AppColors.muted,
                fontSize: 12,
                height: 1.45,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _GlassSurface extends StatelessWidget {
  const _GlassSurface({required this.child, required this.padding});

  final Widget child;
  final EdgeInsetsGeometry padding;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(30),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 22, sigmaY: 22),
        child: Container(
          padding: padding,
          decoration: BoxDecoration(
            color: const Color(0xB30A162A),
            borderRadius: BorderRadius.circular(30),
            border: Border.all(color: AppColors.cyan.withValues(alpha: 0.18)),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.34),
                blurRadius: 44,
                offset: const Offset(0, 24),
              ),
              BoxShadow(
                color: AppColors.cyan.withValues(alpha: 0.08),
                blurRadius: 50,
              ),
            ],
          ),
          child: child,
        ),
      ),
    );
  }
}

class _PremiumTextField extends StatelessWidget {
  const _PremiumTextField({
    required this.controller,
    required this.label,
    required this.icon,
    this.enabled = true,
    this.obscureText = false,
    this.textInputAction,
    this.onSubmitted,
    this.suffixIcon,
  });

  final TextEditingController controller;
  final String label;
  final IconData icon;
  final bool enabled;
  final bool obscureText;
  final TextInputAction? textInputAction;
  final ValueChanged<String>? onSubmitted;
  final Widget? suffixIcon;

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      enabled: enabled,
      obscureText: obscureText,
      textInputAction: textInputAction,
      onSubmitted: onSubmitted,
      style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w700),
      decoration: InputDecoration(
        labelText: label,
        prefixIcon: Icon(icon, color: AppColors.cyan),
        suffixIcon: suffixIcon,
        filled: true,
        fillColor: Colors.white.withValues(alpha: 0.045),
        labelStyle: const TextStyle(color: AppColors.muted),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: BorderSide(color: AppColors.cyan.withValues(alpha: 0.16)),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: BorderSide(color: AppColors.cyan.withValues(alpha: 0.16)),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(18),
          borderSide: const BorderSide(color: AppColors.cyan, width: 1.2),
        ),
      ),
    );
  }
}

class _PremiumActionButton extends StatelessWidget {
  const _PremiumActionButton({
    required this.label,
    required this.busy,
    required this.enabled,
    required this.onPressed,
  });

  final String label;
  final bool busy;
  final bool enabled;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 54,
      child: DecoratedBox(
        decoration: BoxDecoration(
          borderRadius: BorderRadius.circular(999),
          boxShadow: enabled
              ? [
                  BoxShadow(
                    color: AppColors.cyan.withValues(alpha: 0.28),
                    blurRadius: 26,
                    offset: const Offset(0, 12),
                  ),
                ]
              : null,
        ),
        child: FilledButton(
          onPressed: enabled ? onPressed : null,
          style: FilledButton.styleFrom(
            backgroundColor: AppColors.cyan,
            foregroundColor: const Color(0xFF03131F),
            disabledBackgroundColor: AppColors.cyan.withValues(alpha: 0.18),
            disabledForegroundColor: AppColors.soft.withValues(alpha: 0.45),
            shape: RoundedRectangleBorder(
              borderRadius: BorderRadius.circular(999),
            ),
          ),
          child: Row(
            mainAxisAlignment: MainAxisAlignment.center,
            children: [
              if (busy) ...[
                const SizedBox(
                  width: 18,
                  height: 18,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: Color(0xFF03131F),
                  ),
                ),
                const SizedBox(width: 12),
              ] else ...[
                const Icon(Icons.fingerprint, size: 21),
                const SizedBox(width: 10),
              ],
              Text(
                label,
                style: const TextStyle(
                  fontWeight: FontWeight.w900,
                  letterSpacing: 0,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _StatusPill extends StatelessWidget {
  const _StatusPill({required this.message, required this.color});

  final String message;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 9),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.1),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.28)),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: color,
              boxShadow: [BoxShadow(color: color, blurRadius: 12)],
            ),
          ),
          const SizedBox(width: 9),
          Flexible(
            child: Text(
              message,
              style: TextStyle(
                color: color == AppColors.green ? AppColors.soft : color,
                fontSize: 12,
                fontWeight: FontWeight.w800,
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _NetworkPulse extends StatelessWidget {
  const _NetworkPulse({required this.progress});

  final double progress;

  @override
  Widget build(BuildContext context) {
    final scale = 0.82 + math.sin(progress * math.pi * 2) * 0.08;
    return Transform.scale(
      scale: scale,
      child: Container(
        width: 12,
        height: 12,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: AppColors.green,
          boxShadow: [
            BoxShadow(
              color: AppColors.green.withValues(alpha: 0.45),
              blurRadius: 18,
            ),
          ],
        ),
      ),
    );
  }
}

class SegmentedOtpField extends StatefulWidget {
  const SegmentedOtpField({
    required this.controller,
    this.enabled = true,
    this.onSubmitted,
    super.key,
  });

  final TextEditingController controller;
  final bool enabled;
  final ValueChanged<String>? onSubmitted;

  @override
  State<SegmentedOtpField> createState() => _SegmentedOtpFieldState();
}

class _SegmentedOtpFieldState extends State<SegmentedOtpField> {
  final focusNode = FocusNode();

  @override
  void initState() {
    super.initState();
    widget.controller.addListener(_refresh);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      Future<void>.delayed(const Duration(milliseconds: 100), () {
        if (mounted && widget.enabled) focusNode.requestFocus();
      });
    });
  }

  @override
  void dispose() {
    widget.controller.removeListener(_refresh);
    focusNode.dispose();
    super.dispose();
  }

  void _refresh() => setState(() {});

  @override
  Widget build(BuildContext context) {
    final text = widget.controller.text;
    return GestureDetector(
      onTap: widget.enabled ? () => focusNode.requestFocus() : null,
      child: Stack(
        alignment: Alignment.center,
        children: [
          Opacity(
            opacity: 0.01,
            child: TextField(
              controller: widget.controller,
              focusNode: focusNode,
              enabled: widget.enabled,
              autofocus: true,
              keyboardType: TextInputType.number,
              textInputAction: TextInputAction.done,
              enableSuggestions: false,
              autocorrect: false,
              inputFormatters: [
                FilteringTextInputFormatter.digitsOnly,
                LengthLimitingTextInputFormatter(6),
              ],
              onSubmitted: widget.onSubmitted,
            ),
          ),
          LayoutBuilder(
            builder: (context, constraints) {
              final gap = constraints.maxWidth < 340 ? 5.0 : 7.0;
              final cellWidth = ((constraints.maxWidth - (gap * 5)) / 6).clamp(
                32.0,
                42.0,
              );
              return Row(
                mainAxisAlignment: MainAxisAlignment.center,
                children: List.generate(6, (index) {
                  final filled = index < text.length;
                  return AnimatedContainer(
                    duration: const Duration(milliseconds: 180),
                    width: cellWidth,
                    height: 50,
                    margin: EdgeInsets.only(right: index == 5 ? 0 : gap),
                    alignment: Alignment.center,
                    decoration: BoxDecoration(
                      color: filled
                          ? AppColors.cyan.withValues(alpha: 0.13)
                          : Colors.white.withValues(alpha: 0.05),
                      borderRadius: BorderRadius.circular(14),
                      border: Border.all(
                        color: filled
                            ? AppColors.cyan
                            : AppColors.cyan.withValues(alpha: 0.18),
                      ),
                      boxShadow: filled
                          ? [
                              BoxShadow(
                                color: AppColors.cyan.withValues(alpha: 0.16),
                                blurRadius: 16,
                              ),
                            ]
                          : null,
                    ),
                    child: Text(
                      filled ? text[index] : '',
                      style: const TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                        fontSize: 20,
                      ),
                    ),
                  );
                }),
              );
            },
          ),
        ],
      ),
    );
  }
}

class _BiometricVisual extends StatelessWidget {
  const _BiometricVisual({required this.progress, required this.compact});

  final double progress;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    final size = compact ? 190.0 : 360.0;
    return SizedBox(
      width: size,
      height: size,
      child: CustomPaint(painter: _BiometricVisualPainter(progress)),
    );
  }
}

class _BiometricVisualPainter extends CustomPainter {
  const _BiometricVisualPainter(this.progress);

  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final radius = size.shortestSide * 0.34;
    final cyanPaint = Paint()
      ..color = AppColors.cyan
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.4
      ..strokeCap = StrokeCap.round
      ..maskFilter = const MaskFilter.blur(BlurStyle.solid, 1.5);
    final softPaint = Paint()
      ..color = AppColors.cyan.withValues(alpha: 0.18)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.0;

    canvas.drawOval(
      Rect.fromCenter(
        center: center,
        width: size.width * 0.82,
        height: size.height * 0.42,
      ),
      cyanPaint,
    );
    canvas.drawCircle(center, radius * (1.1 + progress * 0.08), softPaint);

    for (var i = 0; i < 6; i++) {
      final angle = (math.pi * 2 / 6) * i + progress * math.pi * 2;
      final point = Offset(
        center.dx + math.cos(angle) * radius,
        center.dy + math.sin(angle) * radius,
      );
      final nextAngle = (math.pi * 2 / 6) * (i + 1) + progress * math.pi * 2;
      final next = Offset(
        center.dx + math.cos(nextAngle) * radius,
        center.dy + math.sin(nextAngle) * radius,
      );
      canvas.drawLine(point, next, cyanPaint);
      canvas.drawCircle(point, 3.2, Paint()..color = AppColors.cyan);
    }

    for (var i = 0; i < 38; i++) {
      final angle = i / 38 * math.pi * 2;
      final inner = radius * 0.47;
      final outer = inner + 10 + math.sin(progress * math.pi * 2 + i) * 3;
      canvas.drawLine(
        Offset(
          center.dx + math.cos(angle) * inner,
          center.dy + math.sin(angle) * inner,
        ),
        Offset(
          center.dx + math.cos(angle) * outer,
          center.dy + math.sin(angle) * outer,
        ),
        softPaint..color = AppColors.cyan.withValues(alpha: 0.42),
      );
    }

    final scanY =
        center.dy - size.height * 0.22 + progress * size.height * 0.44;
    canvas.drawLine(
      Offset(size.width * 0.14, scanY),
      Offset(size.width * 0.86, scanY),
      Paint()
        ..shader = const LinearGradient(
          colors: [Colors.transparent, AppColors.cyan, Colors.transparent],
        ).createShader(Rect.fromLTWH(0, scanY - 10, size.width, 20))
        ..strokeWidth = 2.0
        ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 4),
    );

    final shield = Path()
      ..moveTo(center.dx, center.dy - 34)
      ..lineTo(center.dx + 34, center.dy - 20)
      ..quadraticBezierTo(
        center.dx + 30,
        center.dy + 26,
        center.dx,
        center.dy + 42,
      )
      ..quadraticBezierTo(
        center.dx - 30,
        center.dy + 26,
        center.dx - 34,
        center.dy - 20,
      )
      ..close();
    canvas.drawPath(
      shield,
      Paint()
        ..color = Colors.white.withValues(alpha: 0.08)
        ..style = PaintingStyle.fill,
    );
    canvas.drawPath(
      shield,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 4
        ..strokeJoin = StrokeJoin.round,
    );
    final check = Path()
      ..moveTo(center.dx - 16, center.dy + 2)
      ..lineTo(center.dx - 3, center.dy + 16)
      ..lineTo(center.dx + 22, center.dy - 14);
    canvas.drawPath(
      check,
      Paint()
        ..color = Colors.white
        ..style = PaintingStyle.stroke
        ..strokeWidth = 6
        ..strokeCap = StrokeCap.round
        ..strokeJoin = StrokeJoin.round,
    );
  }

  @override
  bool shouldRepaint(covariant _BiometricVisualPainter oldDelegate) =>
      oldDelegate.progress != progress;
}

class _ParticleFieldPainter extends CustomPainter {
  const _ParticleFieldPainter(this.progress);

  final double progress;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()..color = AppColors.cyan.withValues(alpha: 0.15);
    for (var i = 0; i < 34; i++) {
      final seed = i * 37.0;
      final x = (math.sin(seed) * 0.5 + 0.5) * size.width;
      final y =
          ((math.cos(seed * 1.3) * 0.5 + 0.5) * size.height +
              progress * (20 + i % 7 * 6)) %
          size.height;
      canvas.drawCircle(Offset(x, y), 1 + (i % 4) * 0.45, paint);
    }
  }

  @override
  bool shouldRepaint(covariant _ParticleFieldPainter oldDelegate) =>
      oldDelegate.progress != progress;
}

class DashboardPage extends StatelessWidget {
  const DashboardPage({required this.students, required this.logs, super.key});

  final List<StudentRecord> students;
  final List<VerificationRecord> logs;

  @override
  Widget build(BuildContext context) {
    final verified = logs
        .where((row) => row.status == VerificationStatus.verified)
        .length;
    final failed = logs
        .where((row) => row.status == VerificationStatus.notVerified)
        .length;
    final width = MediaQuery.sizeOf(context).width;
    final crossAxisCount = width >= 1180
        ? 4
        : width >= 720
        ? 2
        : 1;

    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'Operations Dashboard',
            subtitle:
                'Monitor registrations, verification attempts, and recent exam-entry decisions.',
          ),
          const SectionTitle(
            title: 'Command Metrics',
            subtitle: 'Current platform activity and verification outcomes.',
          ),
          GridView.count(
            crossAxisCount: crossAxisCount,
            crossAxisSpacing: 14,
            mainAxisSpacing: 14,
            childAspectRatio: 2.25,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            children: [
              MetricCard(
                label: 'Registered students',
                value: '${students.length}',
                accent: AppColors.cyan,
              ),
              MetricCard(
                label: 'Verification attempts',
                value: '${logs.length}',
                accent: AppColors.sky,
              ),
              MetricCard(
                label: 'Verified',
                value: '$verified',
                accent: AppColors.green,
              ),
              MetricCard(
                label: 'Not verified',
                value: '$failed',
                accent: AppColors.red,
              ),
            ],
          ),
          const SizedBox(height: 20),
          GridView.count(
            crossAxisCount: width >= 1080 ? 3 : 1,
            crossAxisSpacing: 14,
            mainAxisSpacing: 14,
            childAspectRatio: width >= 1080 ? 2.4 : 3.2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            children: [
              const FeatureCard(
                title: 'Identity Engine',
                value: 'Biometric matching active',
                icon: Icons.lock_outline,
              ),
              FeatureCard(
                title: 'Eligible Students',
                value:
                    '${students.where((row) => row.eligible).length} cleared',
                icon: Icons.verified_outlined,
              ),
              FeatureCard(
                title: 'Audit Mode',
                value: '${logs.length} records',
                icon: Icons.receipt_long_outlined,
              ),
            ],
          ),
          const SectionTitle(
            title: 'Recent Verification Attempts',
            subtitle: 'Latest exam-entry decisions recorded by the system.',
          ),
          if (logs.isEmpty)
            const EmptyState(message: 'No verification attempts yet.')
          else
            for (final log in logs.take(5)) VerificationLogCard(record: log),
        ],
      ),
    );
  }
}

class RegisterPage extends StatefulWidget {
  const RegisterPage({
    required this.onStudentRegistered,
    required this.onlineMode,
    super.key,
  });

  final Future<void> Function(StudentRecord student) onStudentRegistered;
  final bool onlineMode;

  @override
  State<RegisterPage> createState() => _RegisterPageState();
}

class _RegisterPageState extends State<RegisterPage> {
  final formKey = GlobalKey<FormState>();
  final studentNumberController = TextEditingController();
  final fullNameController = TextEditingController();
  final programController = TextEditingController();
  final noteController = TextEditingController();
  bool eligible = true;
  bool saving = false;
  File? referencePhoto;
  String? helperMessage;
  bool get mobileCameraAvailable => Platform.isAndroid || Platform.isIOS;
  bool get desktopCameraAvailable => Platform.isWindows;

  @override
  void dispose() {
    studentNumberController.dispose();
    fullNameController.dispose();
    programController.dispose();
    noteController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'Student Registration',
            subtitle:
                'Enroll students and prepare reference identity records for verification.',
          ),
          const SectionTitle(
            title: 'Enrollment Form',
            subtitle:
                'Enroll each student with live camera liveness checks and an official portrait.',
          ),
          PanelCard(
            child: Form(
              key: formKey,
              child: Column(
                children: [
                  AppTextField(
                    controller: studentNumberController,
                    label: 'Student number',
                  ),
                  const SizedBox(height: 12),
                  AppTextField(
                    controller: fullNameController,
                    label: 'Full name',
                  ),
                  const SizedBox(height: 12),
                  AppTextField(
                    controller: programController,
                    label: 'Program / class',
                  ),
                  const SizedBox(height: 12),
                  AppTextField(
                    controller: noteController,
                    label: 'Eligibility note',
                    required: false,
                  ),
                  const SizedBox(height: 12),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    value: eligible,
                    activeThumbColor: AppColors.green,
                    title: const Text('Eligible to write exam'),
                    subtitle: const Text(
                      'This controls whether a verified student may enter.',
                      style: TextStyle(color: AppColors.muted),
                    ),
                    onChanged: (value) => setState(() => eligible = value),
                  ),
                  const Divider(color: AppColors.border),
                  ImageCapturePanel(
                    title: 'Live Biometric Enrollment',
                    subtitle: mobileCameraAvailable || desktopCameraAvailable
                        ? 'Start the camera challenge. Gallery and static image enrollment are disabled for security.'
                        : 'A live camera is required for biometric enrollment.',
                    imageFile: referencePhoto,
                    onCamera: mobileCameraAvailable || desktopCameraAvailable
                        ? _captureReference
                        : null,
                    cameraLabel: referencePhoto == null
                        ? 'Start Enrollment'
                        : 'Retake Enrollment',
                  ),
                  if (helperMessage != null) ...[
                    const SizedBox(height: 12),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: Text(
                        helperMessage!,
                        style: const TextStyle(color: AppColors.muted),
                      ),
                    ),
                  ],
                  const SizedBox(height: 18),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed: saving ? null : _submit,
                      icon: saving
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.person_add_alt_1),
                      label: Text(
                        saving ? 'Preparing record...' : 'Save student record',
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _captureReference() async {
    setState(() {
      helperMessage = 'Starting active liveness enrollment...';
    });
    final captured = await showBiometricScanner(
      context,
      mode: BiometricScanMode.enrollment,
    );
    if (!mounted) return;
    if (captured == null) {
      setState(() => helperMessage = 'Enrollment cancelled.');
      return;
    }
    setState(() {
      referencePhoto = captured;
      helperMessage =
          'Official portrait captured. Face check runs when saving.';
    });
  }

  Future<void> _submit() async {
    if (!formKey.currentState!.validate()) return;
    if (referencePhoto == null) {
      setState(() => helperMessage = 'Add a reference photo before saving.');
      return;
    }

    setState(() {
      saving = true;
      helperMessage = 'Detecting face and creating offline signature...';
    });

    try {
      final studentNumber = studentNumberController.text.trim();
      final storedPhoto = await ExamVerifyFiles.saveStudentPhoto(
        referencePhoto!,
        studentNumber,
        'reference',
      );
      late final List<double> signature;
      if (Platform.isWindows) {
        setState(() {
          helperMessage = 'Creating MobileFaceNet signature on desktop...';
        });
        signature = await PythonFaceBackend.createMobileSignature(
          storedPhoto.path,
        );
      } else {
        signature = await FaceEngine.createSignature(storedPhoto);
      }
      await widget.onStudentRegistered(
        StudentRecord(
          studentNumber: studentNumber,
          fullName: fullNameController.text.trim(),
          program: programController.text.trim(),
          eligible: eligible,
          note: noteController.text.trim(),
          photoPath: storedPhoto.path,
          signature: signature,
          backendName: FaceEngine.signatureBackend,
        ),
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Student record saved locally.')),
      );
      studentNumberController.clear();
      fullNameController.clear();
      programController.clear();
      noteController.clear();
      setState(() {
        referencePhoto = null;
        helperMessage = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => helperMessage = error.toString());
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }
}

class VerifyPage extends StatefulWidget {
  const VerifyPage({
    required this.students,
    required this.examSessions,
    required this.examEligibilities,
    required this.onVerificationSaved,
    this.onlineClient,
    super.key,
  });

  final List<StudentRecord> students;
  final List<ExamSessionRecord> examSessions;
  final List<ExamEligibilityRecord> examEligibilities;
  final Future<void> Function(VerificationRecord record) onVerificationSaved;
  final OnlineBackendClient? onlineClient;

  @override
  State<VerifyPage> createState() => _VerifyPageState();
}

class _VerifyPageState extends State<VerifyPage> {
  StudentRecord? selectedStudent;
  ExamSessionRecord? selectedSession;
  File? livePhoto;
  String? resultMessage;
  VerificationStatus? resultStatus;
  double? resultScore;
  bool verifying = false;
  bool get mobileCameraAvailable => Platform.isAndroid || Platform.isIOS;
  bool get desktopCameraAvailable => Platform.isWindows;

  @override
  Widget build(BuildContext context) {
    selectedStudent ??= widget.students.isEmpty ? null : widget.students.first;
    selectedSession ??= widget.examSessions
        .where((row) => row.isActive)
        .firstOrNull;

    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'Exam Verification',
            subtitle:
                'Capture a live face and compare it with the selected student record offline.',
          ),
          const SectionTitle(
            title: 'Student Lookup',
            subtitle:
                'The device validates face presence, computes a local signature, and stores the result.',
          ),
          if (widget.students.isEmpty)
            const EmptyState(message: 'Register a student before verification.')
          else if (widget.examSessions.where((row) => row.isActive).isEmpty)
            const EmptyState(
              message: 'Activate an exam session before verifying exam entry.',
            )
          else
            PanelCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _ExamSessionSelector(
                    sessions: widget.examSessions
                        .where((row) => row.isActive)
                        .toList(),
                    selected: selectedSession,
                    onChanged: (value) =>
                        setState(() => selectedSession = value),
                  ),
                  const SizedBox(height: 16),
                  DropdownButtonFormField<StudentRecord>(
                    initialValue: selectedStudent,
                    decoration: const InputDecoration(
                      labelText: 'Select student',
                    ),
                    items: [
                      for (final student in widget.students)
                        DropdownMenuItem(
                          value: student,
                          child: Text(
                            '${student.studentNumber} - ${student.fullName}',
                          ),
                        ),
                    ],
                    onChanged: (value) =>
                        setState(() => selectedStudent = value),
                  ),
                  const SizedBox(height: 16),
                  if (selectedStudent != null)
                    StudentInfoPane(student: selectedStudent!),
                  const SizedBox(height: 18),
                  ImageCapturePanel(
                    title: 'Live Verification Photo',
                    subtitle: mobileCameraAvailable || desktopCameraAvailable
                        ? 'Capture the student standing at the exam room.'
                        : 'A live camera is required for biometric verification.',
                    imageFile: livePhoto,
                    onCamera: mobileCameraAvailable || desktopCameraAvailable
                        ? _captureLivePhoto
                        : null,
                    cameraLabel: 'Start Scanner',
                  ),
                  if (resultMessage != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      resultMessage!,
                      style: const TextStyle(color: AppColors.muted),
                    ),
                  ],
                  if (resultStatus != null) ...[
                    const SizedBox(height: 16),
                    AutoIdentifyResultPanel(
                      student: selectedStudent,
                      status: resultStatus!,
                      score: resultScore ?? 0,
                      imageFile: livePhoto,
                    ),
                  ],
                  const SizedBox(height: 18),
                  SizedBox(
                    width: double.infinity,
                    child: FilledButton.icon(
                      onPressed:
                          verifying ||
                              selectedStudent == null ||
                              selectedSession == null ||
                              livePhoto == null
                          ? null
                          : _verifySelectedStudent,
                      icon: verifying
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.verified_user_outlined),
                      label: Text(
                        verifying ? 'Verifying...' : 'Verify student',
                      ),
                    ),
                  ),
                ],
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _captureLivePhoto() async {
    final captured = await showBiometricScanner(
      context,
      mode: BiometricScanMode.verification,
    );
    if (captured == null) return;
    setState(() {
      livePhoto = captured;
      resultMessage = 'Live biometric scan captured. Tap verify to compare.';
      resultStatus = null;
      resultScore = null;
    });
  }

  Future<void> _verifySelectedStudent() async {
    final student = selectedStudent;
    final session = selectedSession;
    final photo = livePhoto;
    if (student == null || session == null || photo == null) return;

    setState(() {
      verifying = true;
      resultMessage = 'Analyzing face and comparing signatures...';
    });

    try {
      final storedLivePhoto = await ExamVerifyFiles.saveStudentPhoto(
        photo,
        student.studentNumber,
        'live',
      );
      final liveness = await FaceEngine.checkLiveness(storedLivePhoto);
      if (!liveness.passed) {
        await widget.onVerificationSaved(
          VerificationRecord(
            time: DateTime.now(),
            studentNumber: student.studentNumber,
            fullName: student.fullName,
            program: student.program,
            status: VerificationStatus.spoofDetected,
            score: liveness.score,
            capturedImagePath: storedLivePhoto.path,
            storedImagePath: student.photoPath,
            mode: 'Mobile liveness',
          ),
        );
        if (!mounted) return;
        setState(() {
          resultStatus = VerificationStatus.spoofDetected;
          resultScore = liveness.score;
          resultMessage = 'Spoof detected: ${liveness.message}';
        });
        await ExamVerifyFeedback.playVerificationTone(
          VerificationStatus.spoofDetected,
        );
        return;
      }
      final liveSignature = await FaceEngine.createSignature(storedLivePhoto);
      if (!FaceEngine.canCompareSignatures(student.signature, liveSignature)) {
        throw FaceEngineException(
          'This student does not have a compatible MobileFaceNet profile. Sync or re-enroll the student using the mobile scanner.',
        );
      }
      final ranked = [
        for (final candidate in widget.students)
          if (FaceEngine.canCompareSignatures(
            candidate.signature,
            liveSignature,
          ))
            MapEntry(
              candidate,
              FaceEngine.distance(candidate.signature, liveSignature),
            ),
      ]..sort((a, b) => a.value.compareTo(b.value));
      final selectedMatch = ranked.firstWhere(
        (match) => match.key.studentNumber == student.studentNumber,
        orElse: () => MapEntry(
          student,
          FaceEngine.distance(student.signature, liveSignature),
        ),
      );
      final score = selectedMatch.value;
      final selectedIsBest =
          ranked.isNotEmpty &&
          ranked.first.key.studentNumber == student.studentNumber;
      final selectedHasGap =
          ranked.length <= 1 ||
          (selectedIsBest &&
              ranked[1].value - score >= FaceEngine.verificationMinimumGap);
      final verified =
          selectedIsBest &&
          selectedHasGap &&
          score <= FaceEngine.verificationThreshold &&
          student.eligible;
      final eligibility = _eligibilityFor(session, student);
      final sessionAllowed =
          verified &&
          student.status == 'active' &&
          eligibility != null &&
          eligibility.eligibilityStatus == 'eligible' &&
          eligibility.attendanceStatus != 'verified';
      final cloudDecision = widget.onlineClient == null
          ? null
          : await widget.onlineClient!.evaluateExamEntry(
              sessionId: session.id,
              student: student,
              matchScore: score,
              confidenceGap: ranked.length > 1 ? ranked[1].value - score : 1,
              matchThreshold: FaceEngine.verificationThreshold,
              minimumConfidenceGap: FaceEngine.verificationMinimumGap,
              livenessPassed: true,
              identityMatched: selectedIsBest,
              deviceType: Platform.isWindows ? 'desktop' : 'mobile',
            );
      final approved = cloudDecision?.verified ?? sessionAllowed;
      final finalStatus = approved
          ? VerificationStatus.verified
          : VerificationStatus.notVerified;
      await widget.onVerificationSaved(
        VerificationRecord(
          time: DateTime.now(),
          studentNumber: student.studentNumber,
          fullName: student.fullName,
          program: student.program,
          status: finalStatus,
          score: score,
          capturedImagePath: storedLivePhoto.path,
          storedImagePath: student.photoPath,
          mode: '${FaceEngine.signatureBackend} / ${session.courseCode}',
        ),
      );
      if (!mounted) return;
      setState(() {
        resultStatus = finalStatus;
        resultScore = score;
        resultMessage = approved
            ? 'Verified ${student.fullName} for ${session.courseCode}. Eligibility: ${cloudDecision?.eligibilityType ?? eligibility?.eligibilityType ?? 'regular'}.'
            : cloudDecision != null
            ? cloudDecision.reason
            : !selectedIsBest
            ? 'Not verified: the live face does not match the selected student.'
            : !selectedHasGap
            ? 'Not verified: identity confidence is not unique enough. Use the student record for manual confirmation.'
            : eligibility == null
            ? 'Access denied: ${student.fullName} is registered but not eligible for ${session.courseCode}.'
            : eligibility.attendanceStatus == 'verified'
            ? 'Already verified for ${session.courseCode}.'
            : 'Not verified. The biometric score or eligibility check failed.';
      });
      await ExamVerifyFeedback.playVerificationTone(finalStatus);
    } catch (error) {
      if (!mounted) return;
      setState(() => resultMessage = error.toString());
      await ExamVerifyFeedback.playVerificationTone(
        VerificationStatus.notVerified,
      );
    } finally {
      if (mounted) setState(() => verifying = false);
    }
  }

  ExamEligibilityRecord? _eligibilityFor(
    ExamSessionRecord session,
    StudentRecord student,
  ) {
    final studentId = student.id;
    if (studentId == null) return null;
    return widget.examEligibilities.firstWhereOrNull(
      (row) => row.examSessionId == session.id && row.studentId == studentId,
    );
  }
}

class AutoIdentifyPage extends StatefulWidget {
  const AutoIdentifyPage({
    required this.students,
    required this.examSessions,
    required this.examEligibilities,
    required this.onVerificationSaved,
    this.onlineClient,
    super.key,
  });

  final List<StudentRecord> students;
  final List<ExamSessionRecord> examSessions;
  final List<ExamEligibilityRecord> examEligibilities;
  final Future<void> Function(VerificationRecord record) onVerificationSaved;
  final OnlineBackendClient? onlineClient;

  @override
  State<AutoIdentifyPage> createState() => _AutoIdentifyPageState();
}

class _AutoIdentifyPageState extends State<AutoIdentifyPage> {
  File? livePhoto;
  ExamSessionRecord? selectedSession;
  String? resultMessage;
  StudentRecord? resultStudent;
  VerificationStatus? resultStatus;
  double? resultScore;
  bool identifying = false;
  bool get mobileCameraAvailable => Platform.isAndroid || Platform.isIOS;
  bool get desktopCameraAvailable => Platform.isWindows;

  @override
  Widget build(BuildContext context) {
    selectedSession ??= widget.examSessions
        .where((row) => row.isActive)
        .firstOrNull;
    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'Auto Identify',
            subtitle:
                'Open the biometric scanner and identify students in real time.',
          ),
          const SectionTitle(
            title: 'Live Scanning',
            subtitle:
                'Liveness checks run before the closest stored biometric profile is selected.',
          ),
          if (widget.students.isEmpty)
            const EmptyState(message: 'No student records available.')
          else if (widget.examSessions.where((row) => row.isActive).isEmpty)
            const EmptyState(
              message: 'Activate an exam session before auto-identify starts.',
            )
          else
            PanelCard(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _ExamSessionSelector(
                    sessions: widget.examSessions
                        .where((row) => row.isActive)
                        .toList(),
                    selected: selectedSession,
                    onChanged: (value) =>
                        setState(() => selectedSession = value),
                  ),
                  const SizedBox(height: 16),
                  if (desktopCameraAvailable)
                    _DesktopAutoIdentifyKiosk(
                      students: widget.students,
                      onIdentifyFrame: _identifyCapturedPhoto,
                      resultStudent: resultStudent,
                      resultStatus: resultStatus,
                      resultScore: resultScore,
                    )
                  else
                    ImageCapturePanel(
                      title: 'Live Identification Photo',
                      subtitle: mobileCameraAvailable
                          ? 'Capture a live face without selecting a student first.'
                          : 'A live camera is required for automatic identification.',
                      imageFile: livePhoto,
                      onCamera: mobileCameraAvailable
                          ? _captureLivePhoto
                          : null,
                      cameraLabel: 'Start Scanner',
                    ),
                  if (resultMessage != null) ...[
                    const SizedBox(height: 12),
                    Text(
                      resultMessage!,
                      style: const TextStyle(color: AppColors.muted),
                    ),
                  ],
                  if (resultStatus != null) ...[
                    const SizedBox(height: 16),
                    AutoIdentifyResultPanel(
                      student: resultStudent,
                      status: resultStatus!,
                      score: resultScore ?? 0,
                      imageFile: livePhoto,
                    ),
                  ],
                  if (!desktopCameraAvailable) ...[
                    const SizedBox(height: 18),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        onPressed: identifying ? null : _captureLivePhoto,
                        icon: identifying
                            ? const SizedBox(
                                height: 18,
                                width: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.center_focus_strong_outlined),
                        label: Text(
                          identifying
                              ? 'Scanning records...'
                              : 'Start biometric scan',
                        ),
                      ),
                    ),
                  ],
                  if (!desktopCameraAvailable) ...[
                    const SizedBox(height: 18),
                    const Divider(color: AppColors.border),
                    const SizedBox(height: 10),
                    for (final student in widget.students.take(5))
                      Padding(
                        padding: const EdgeInsets.only(bottom: 10),
                        child: StudentInfoPane(student: student),
                      ),
                  ],
                ],
              ),
            ),
        ],
      ),
    );
  }

  Future<void> _captureLivePhoto() async {
    final captured = await showBiometricScanner(
      context,
      mode: BiometricScanMode.autoIdentify,
    );
    if (captured == null) return;
    setState(() {
      livePhoto = captured;
      resultMessage = 'Live biometric scan captured. Searching records...';
      resultStudent = null;
      resultStatus = null;
      resultScore = null;
    });
    await _identifyCapturedPhoto(captured);
  }

  Future<_AutoIdentifyOutcome> _identifyCapturedPhoto(File photo) async {
    if (widget.students.isEmpty) {
      return const _AutoIdentifyOutcome(
        status: VerificationStatus.notVerified,
        score: 1,
        message: 'No student records are available.',
      );
    }
    final session = selectedSession;
    if (session == null) {
      return const _AutoIdentifyOutcome(
        status: VerificationStatus.notVerified,
        score: 1,
        message: 'No active exam session selected.',
      );
    }

    setState(() {
      identifying = true;
      resultMessage = 'Building live signature and ranking stored records...';
    });

    try {
      final storedLivePhoto = await ExamVerifyFiles.saveStudentPhoto(
        photo,
        'auto',
        'identify',
      );
      if (mounted) setState(() => livePhoto = storedLivePhoto);
      final liveness = await FaceEngine.checkLiveness(storedLivePhoto);
      if (!liveness.passed) {
        await widget.onVerificationSaved(
          VerificationRecord(
            time: DateTime.now(),
            studentNumber: 'UNKNOWN',
            fullName: 'Spoof attempt',
            program: '',
            status: VerificationStatus.spoofDetected,
            score: liveness.score,
            capturedImagePath: storedLivePhoto.path,
            mode: 'Mobile liveness',
          ),
        );
        if (mounted) {
          setState(() {
            resultStudent = null;
            resultStatus = VerificationStatus.spoofDetected;
            resultScore = liveness.score;
            resultMessage = 'Spoof detected: ${liveness.message}';
          });
        }
        await _playVerificationTone(VerificationStatus.spoofDetected);
        return _AutoIdentifyOutcome(
          status: VerificationStatus.spoofDetected,
          score: liveness.score,
          message: 'Spoof detected: ${liveness.message}',
        );
      }
      if (Platform.isWindows) {
        if (!widget.students.any(
          (student) => student.signature.length == 192,
        )) {
          throw FaceEngineException(
            'No compatible MobileFaceNet profiles are available. Sync or enroll a student with the mobile scanner first.',
          );
        }
      }
      final liveSignature = await FaceEngine.createSignature(storedLivePhoto);
      final ranked = [
        for (final student in widget.students)
          if (FaceEngine.canCompareSignatures(student.signature, liveSignature))
            MapEntry(
              student,
              FaceEngine.distance(student.signature, liveSignature),
            ),
      ]..sort((a, b) => a.value.compareTo(b.value));

      StudentRecord? bestStudent;
      double bestScore = 1;
      double? secondScore;
      if (ranked.isNotEmpty) {
        final best = ranked.first;
        bestStudent = best.key;
        bestScore = best.value;
        secondScore = ranked.length > 1 ? ranked[1].value : null;
      }
      final hasGap =
          secondScore == null ||
          secondScore - bestScore >= FaceEngine.identificationMinimumGap;
      final verified =
          bestStudent != null &&
          bestScore <= FaceEngine.identificationThreshold &&
          hasGap &&
          bestStudent.eligible;
      final eligibility = bestStudent == null
          ? null
          : _eligibilityFor(session, bestStudent);
      final sessionAllowed =
          verified &&
          bestStudent.status == 'active' &&
          eligibility != null &&
          eligibility.eligibilityStatus == 'eligible' &&
          eligibility.attendanceStatus != 'verified';
      final cloudDecision = widget.onlineClient == null
          ? null
          : await widget.onlineClient!.evaluateExamEntry(
              sessionId: session.id,
              student: bestStudent,
              matchScore: bestScore,
              confidenceGap: secondScore == null ? 1 : secondScore - bestScore,
              matchThreshold: FaceEngine.identificationThreshold,
              minimumConfidenceGap: FaceEngine.identificationMinimumGap,
              livenessPassed: true,
              identityMatched: verified,
              deviceType: Platform.isWindows ? 'desktop' : 'mobile',
            );
      final approved = cloudDecision?.verified ?? sessionAllowed;
      await widget.onVerificationSaved(
        VerificationRecord(
          time: DateTime.now(),
          studentNumber: bestStudent?.studentNumber ?? 'UNKNOWN',
          fullName: bestStudent?.fullName ?? 'Unknown face',
          program: bestStudent?.program ?? '',
          status: approved
              ? VerificationStatus.verified
              : VerificationStatus.notVerified,
          score: bestScore,
          capturedImagePath: storedLivePhoto.path,
          storedImagePath: bestStudent?.photoPath,
          mode: '${FaceEngine.signatureBackend} / ${session.courseCode}',
        ),
      );
      final matchedName = bestStudent?.fullName ?? 'Student';
      final matchedNumber = bestStudent?.studentNumber ?? 'UNKNOWN';
      final message = approved
          ? 'Verified $matchedName. Student ID $matchedNumber.'
          : cloudDecision != null
          ? cloudDecision.reason
          : ranked.isEmpty
          ? 'No compatible MobileFaceNet profiles found. Sync or enroll students with the mobile scanner.'
          : !hasGap
          ? 'Unauthorized: identity confidence is not unique enough. Use manual student record confirmation.'
          : bestStudent != null && eligibility == null
          ? 'Access denied: $matchedName is registered but not eligible for ${session.courseCode}.'
          : bestStudent != null && eligibility?.attendanceStatus == 'verified'
          ? 'Already verified: $matchedName was already verified for ${session.courseCode}.'
          : 'Unauthorized: no trusted student profile matched this scan.';
      if (mounted) {
        setState(() {
          resultStudent = bestStudent;
          resultStatus = approved
              ? VerificationStatus.verified
              : VerificationStatus.notVerified;
          resultScore = bestScore;
          resultMessage = message;
        });
      }
      final outcome = _AutoIdentifyOutcome(
        status: approved
            ? VerificationStatus.verified
            : VerificationStatus.notVerified,
        student: bestStudent,
        score: bestScore,
        message: message,
      );
      await _playVerificationTone(outcome.status);
      return outcome;
    } catch (error) {
      final message = error.toString();
      if (mounted) setState(() => resultMessage = message);
      await _playVerificationTone(VerificationStatus.notVerified);
      return _AutoIdentifyOutcome(
        status: VerificationStatus.notVerified,
        score: 1,
        message: message,
      );
    } finally {
      if (mounted) setState(() => identifying = false);
    }
  }

  ExamEligibilityRecord? _eligibilityFor(
    ExamSessionRecord session,
    StudentRecord student,
  ) {
    final studentId = student.id;
    if (studentId == null) return null;
    return widget.examEligibilities.firstWhereOrNull(
      (row) => row.examSessionId == session.id && row.studentId == studentId,
    );
  }

  Future<void> _playVerificationTone(VerificationStatus status) async {
    await ExamVerifyFeedback.playVerificationTone(status);
  }
}

class _AutoIdentifyOutcome {
  const _AutoIdentifyOutcome({
    required this.status,
    required this.score,
    required this.message,
    this.student,
  });

  final VerificationStatus status;
  final StudentRecord? student;
  final double score;
  final String message;
}

class ExamVerifyFeedback {
  static Future<void> playVerificationTone(VerificationStatus status) async {
    if (Platform.isWindows) {
      final script = status == VerificationStatus.verified
          ? '[console]::beep(880,180); Start-Sleep -Milliseconds 70; [console]::beep(1175,220)'
          : '[console]::beep(330,240); Start-Sleep -Milliseconds 80; [console]::beep(220,280)';
      await Process.run('powershell.exe', ['-NoProfile', '-Command', script]);
      return;
    }
    final sound = status == VerificationStatus.verified
        ? SystemSoundType.click
        : SystemSoundType.alert;
    await SystemSound.play(sound);
    if (status != VerificationStatus.verified) {
      await Future<void>.delayed(const Duration(milliseconds: 180));
      await SystemSound.play(SystemSoundType.alert);
    }
  }
}

enum _KioskScanPhase {
  idle,
  faceDetected,
  livenessCheck,
  identifying,
  verified,
  rejected,
  cooldown,
  crowdBlocked,
  error,
}

class _DesktopAutoIdentifyKiosk extends StatefulWidget {
  const _DesktopAutoIdentifyKiosk({
    required this.students,
    required this.onIdentifyFrame,
    this.resultStudent,
    this.resultStatus,
    this.resultScore,
  });

  final List<StudentRecord> students;
  final Future<_AutoIdentifyOutcome> Function(File frame) onIdentifyFrame;
  final StudentRecord? resultStudent;
  final VerificationStatus? resultStatus;
  final double? resultScore;

  @override
  State<_DesktopAutoIdentifyKiosk> createState() =>
      _DesktopAutoIdentifyKioskState();
}

class _DesktopAutoIdentifyKioskState extends State<_DesktopAutoIdentifyKiosk>
    with SingleTickerProviderStateMixin {
  camera.CameraController? controller;
  late final AnimationController animation;
  Timer? scanTimer;
  Timer? cooldownTimer;
  _KioskScanPhase phase = _KioskScanPhase.idle;
  FaceSignal? signal;
  String message = 'Idle. Waiting for one student to step into frame.';
  bool previewReady = false;
  bool analyzing = false;
  int stableFrames = 0;
  int livenessFrames = 0;
  static const minimumQuality = 0.62;
  static const minimumPresenceQuality = 0.40;
  static const cooldownDuration = Duration(seconds: 3);

  @override
  void initState() {
    super.initState();
    animation = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    )..repeat();
    _openCamera();
  }

  @override
  void dispose() {
    scanTimer?.cancel();
    cooldownTimer?.cancel();
    controller?.dispose();
    animation.dispose();
    super.dispose();
  }

  Future<void> _openCamera() async {
    try {
      final cameras = await camera.availableCameras();
      if (cameras.isEmpty) {
        setState(() {
          phase = _KioskScanPhase.error;
          message = 'No desktop camera was found.';
        });
        return;
      }
      final selected = cameras.firstWhere(
        (item) => item.lensDirection == camera.CameraLensDirection.front,
        orElse: () => cameras.first,
      );
      final nextController = camera.CameraController(
        selected,
        camera.ResolutionPreset.high,
        enableAudio: false,
      );
      await nextController.initialize();
      if (!mounted) {
        await nextController.dispose();
        return;
      }
      setState(() {
        controller = nextController;
        previewReady = true;
        phase = _KioskScanPhase.idle;
        message = 'Idle. Waiting for one student to step into frame.';
      });
      _startLoop();
    } catch (error) {
      if (!mounted) return;
      setState(() {
        phase = _KioskScanPhase.error;
        message = 'Camera initialization failed: $error';
      });
    }
  }

  void _startLoop() {
    scanTimer?.cancel();
    scanTimer = Timer.periodic(
      const Duration(milliseconds: 520),
      (_) => _analyzeNextFrame(),
    );
  }

  Future<void> _analyzeNextFrame() async {
    final active = controller;
    if (active == null ||
        !active.value.isInitialized ||
        !previewReady ||
        active.value.isTakingPicture ||
        analyzing ||
        phase == _KioskScanPhase.cooldown ||
        phase == _KioskScanPhase.identifying ||
        phase == _KioskScanPhase.livenessCheck ||
        phase == _KioskScanPhase.error) {
      return;
    }
    analyzing = true;
    File? frame;
    try {
      final image = await active.takePicture();
      frame = File(image.path);
      final nextSignal = await FaceEngine.analyzeFaceSignal(frame);
      if (!mounted) return;
      signal = nextSignal;
      final strongSingleFace =
          nextSignal.faceCount == 1 &&
          nextSignal.quality >= minimumPresenceQuality &&
          nextSignal.poseReliable;
      if (nextSignal.faceCount > 1) {
        stableFrames = 0;
        livenessFrames = 0;
        setState(() {
          phase = _KioskScanPhase.crowdBlocked;
          message =
              'Multiple faces detected. Let one student stand in front of the camera.';
        });
        return;
      }
      if (!strongSingleFace) {
        stableFrames = 0;
        livenessFrames = 0;
        setState(() {
          phase = _KioskScanPhase.idle;
          message = nextSignal.faceCount == 1
              ? 'Weak face signal. Step closer and face the camera directly.'
              : 'Idle. Waiting for one student to step into frame.';
        });
        return;
      }
      final centered =
          nextSignal.quality >= minimumQuality &&
          nextSignal.yaw.abs() < 14 &&
          nextSignal.pitch.abs() < 14 &&
          nextSignal.roll.abs() < 14;
      final eyesOpen =
          ((nextSignal.leftEyeOpen + nextSignal.rightEyeOpen) / 2) > 0.34;
      final liveEnough = centered && eyesOpen;
      stableFrames = centered ? stableFrames + 1 : 0;
      livenessFrames = liveEnough ? livenessFrames + 1 : 0;
      if (stableFrames < 5 || livenessFrames < 4) {
        setState(() {
          phase = _KioskScanPhase.faceDetected;
          message = liveEnough
              ? 'Face detected. Hold still for liveness confirmation...'
              : 'Face detected. Center face until quality reaches 62% in steady light.';
        });
        return;
      }
      final acceptedFrame = frame;
      frame = null;
      await _identifyAcceptedFrame(acceptedFrame);
    } catch (error) {
      if (mounted) {
        setState(() {
          phase = _KioskScanPhase.error;
          message = 'Scanner interrupted: $error';
        });
      }
    } finally {
      analyzing = false;
      final disposable = frame;
      if (disposable != null) {
        unawaited(disposable.delete().catchError((_) => disposable));
      }
    }
  }

  Future<void> _identifyAcceptedFrame(File frame) async {
    stableFrames = 0;
    livenessFrames = 0;
    setState(() {
      phase = _KioskScanPhase.livenessCheck;
      message = 'Liveness check...';
    });
    await Future<void>.delayed(const Duration(milliseconds: 180));
    if (!mounted) return;
    setState(() {
      phase = _KioskScanPhase.identifying;
      message = 'Identifying student...';
    });
    final outcome = await widget.onIdentifyFrame(frame);
    unawaited(frame.delete().catchError((_) => frame));
    if (!mounted) return;
    setState(() {
      phase = outcome.status == VerificationStatus.verified
          ? _KioskScanPhase.verified
          : _KioskScanPhase.rejected;
      message = outcome.status == VerificationStatus.verified
          ? 'Verified: ${outcome.student?.fullName ?? 'Student'}'
          : 'Rejected. Manual check or retry required.';
    });
    cooldownTimer?.cancel();
    cooldownTimer = Timer(const Duration(milliseconds: 900), _enterCooldown);
  }

  void _enterCooldown() {
    if (!mounted) return;
    setState(() {
      phase = _KioskScanPhase.cooldown;
      message = 'Cooldown. Please let the next student step forward.';
    });
    cooldownTimer?.cancel();
    cooldownTimer = Timer(cooldownDuration, () {
      if (!mounted) return;
      setState(() {
        phase = _KioskScanPhase.idle;
        message = 'Idle. Waiting for one student to step into frame.';
        signal = null;
      });
    });
  }

  Color get _phaseColor => switch (phase) {
    _KioskScanPhase.verified => AppColors.green,
    _KioskScanPhase.rejected ||
    _KioskScanPhase.crowdBlocked ||
    _KioskScanPhase.error => AppColors.red,
    _KioskScanPhase.cooldown => AppColors.amber,
    _ => AppColors.cyan,
  };

  String get _phaseLabel => switch (phase) {
    _KioskScanPhase.idle => 'Idle',
    _KioskScanPhase.faceDetected => 'Face detected',
    _KioskScanPhase.livenessCheck => 'Liveness check',
    _KioskScanPhase.identifying => 'Identifying',
    _KioskScanPhase.verified => 'Verified',
    _KioskScanPhase.rejected => 'Rejected',
    _KioskScanPhase.cooldown => 'Cooldown',
    _KioskScanPhase.crowdBlocked => 'Crowd safety',
    _KioskScanPhase.error => 'Camera error',
  };

  @override
  Widget build(BuildContext context) {
    final active = controller;
    final previewSize = active?.value.previewSize;
    final previewAspect = previewSize == null || previewSize.height == 0
        ? 16 / 9
        : (previewSize.width / previewSize.height).clamp(1.32, 1.90);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Icon(Icons.sensors_outlined, color: _phaseColor),
            const SizedBox(width: 10),
            const Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Continuous Entry Scanner',
                    style: TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w900,
                      fontSize: 16,
                    ),
                  ),
                  Text(
                    'Desktop kiosk mode: one student at a time, stable face, liveness, identify, cooldown.',
                    style: TextStyle(color: AppColors.muted),
                  ),
                ],
              ),
            ),
            StatusPill(label: _phaseLabel, tone: _phaseColor),
          ],
        ),
        const SizedBox(height: 14),
        LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < 860;
            final preview = ClipRRect(
              borderRadius: BorderRadius.circular(18),
              child: AspectRatio(
                aspectRatio: previewAspect,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    if (active != null &&
                        active.value.isInitialized &&
                        previewReady)
                      FittedBox(
                        fit: BoxFit.cover,
                        child: SizedBox(
                          width: active.value.previewSize?.width ?? 720,
                          height: active.value.previewSize?.height ?? 1280,
                          child: camera.CameraPreview(active),
                        ),
                      )
                    else
                      const ColoredBox(
                        color: Color(0xFF071327),
                        child: Center(
                          child: CircularProgressIndicator(
                            color: AppColors.cyan,
                          ),
                        ),
                      ),
                    AnimatedBuilder(
                      animation: animation,
                      builder: (context, _) => CustomPaint(
                        painter: _BiometricScannerPainter(
                          progress: animation.value,
                          statusProgress: signal?.quality ?? 0,
                          signal: signal,
                          challenge: _BiometricChallengeType.centerInitial,
                          desktop: true,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
            final panel = _KioskStatusPanel(
              phaseLabel: _phaseLabel,
              message: message,
              color: _phaseColor,
              signal: signal,
              resultStudent: widget.resultStudent,
              resultStatus: widget.resultStatus,
              resultScore: widget.resultScore,
            );
            if (compact) {
              return Column(
                children: [preview, const SizedBox(height: 12), panel],
              );
            }
            return Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Expanded(flex: 7, child: preview),
                const SizedBox(width: 16),
                Expanded(flex: 4, child: panel),
              ],
            );
          },
        ),
      ],
    );
  }
}

class _KioskStatusPanel extends StatelessWidget {
  const _KioskStatusPanel({
    required this.phaseLabel,
    required this.message,
    required this.color,
    required this.signal,
    required this.resultStudent,
    required this.resultStatus,
    required this.resultScore,
  });

  final String phaseLabel;
  final String message;
  final Color color;
  final FaceSignal? signal;
  final StudentRecord? resultStudent;
  final VerificationStatus? resultStatus;
  final double? resultScore;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.panelWeak,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: color.withValues(alpha: 0.35)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            phaseLabel,
            style: TextStyle(
              color: color,
              fontSize: 20,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 8),
          Text(message, style: const TextStyle(color: AppColors.soft)),
          const SizedBox(height: 16),
          Wrap(
            spacing: 8,
            runSpacing: 8,
            children: [
              _SignalChip(
                label: signal?.facePresent == true
                    ? 'Face tracking box active'
                    : 'Searching',
                color: signal?.facePresent == true
                    ? AppColors.green
                    : AppColors.amber,
              ),
              _SignalChip(
                label: 'Quality ${(((signal?.quality ?? 0) * 100).round())}%',
                color: AppColors.cyan,
              ),
              _SignalChip(
                label:
                    'Pose Y${(signal?.yaw ?? 0).toStringAsFixed(0)} P${(signal?.pitch ?? 0).toStringAsFixed(0)} R${(signal?.roll ?? 0).toStringAsFixed(0)}',
                color: AppColors.cyan,
              ),
              _SignalChip(
                label:
                    'Eyes ${((((signal?.leftEyeOpen ?? 0) + (signal?.rightEyeOpen ?? 0)) / 2) * 100).round()}%',
                color: AppColors.green,
              ),
              _SignalChip(
                label: 'Faces ${signal?.faceCount ?? 0}/1',
                color: (signal?.faceCount ?? 0) <= 1
                    ? AppColors.green
                    : AppColors.red,
              ),
            ],
          ),
          if (resultStatus != null) ...[
            const SizedBox(height: 18),
            const Divider(color: AppColors.border),
            const SizedBox(height: 12),
            Text(
              resultStatus == VerificationStatus.verified
                  ? resultStudent?.fullName ?? 'Verified student'
                  : 'Latest attempt rejected',
              style: const TextStyle(
                color: Colors.white,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 4),
            Text(
              resultStatus == VerificationStatus.verified
                  ? (resultStudent?.program.trim().isEmpty ?? true
                        ? 'Program not recorded'
                        : resultStudent!.program.trim())
                  : 'Manual check or retry required.',
              style: const TextStyle(color: AppColors.muted),
            ),
            if (resultScore != null) ...[
              const SizedBox(height: 8),
              Text(
                'Score ${resultScore!.toStringAsFixed(3)}',
                style: const TextStyle(color: AppColors.cyan),
              ),
            ],
          ],
        ],
      ),
    );
  }
}

class StudentsPage extends StatefulWidget {
  const StudentsPage({
    required this.students,
    required this.onToggleEligibility,
    required this.onDeleteStudent,
    super.key,
  });

  final List<StudentRecord> students;
  final Future<void> Function(StudentRecord student) onToggleEligibility;
  final Future<void> Function(StudentRecord student) onDeleteStudent;

  @override
  State<StudentsPage> createState() => _StudentsPageState();
}

class _StudentsPageState extends State<StudentsPage> {
  final searchController = TextEditingController();

  @override
  void dispose() {
    searchController.dispose();
    super.dispose();
  }

  String get normalizedQuery => _normalizeStudentSearch(searchController.text);

  List<StudentRecord> get filteredStudents {
    final query = normalizedQuery;
    if (query.isEmpty) return widget.students;
    return [
      for (final student in widget.students)
        if (_studentMatchesQuery(student, query)) student,
    ];
  }

  static String _normalizeStudentSearch(String value) {
    return value.toLowerCase().replaceAll(RegExp(r'[^a-z0-9]+'), ' ').trim();
  }

  static bool _studentMatchesQuery(StudentRecord student, String query) {
    final searchable = _normalizeStudentSearch(
      [
        student.fullName,
        student.studentNumber,
        student.program,
        student.note,
        student.studentNumberHash ?? '',
        AuthService.maskIdentifier(student.studentNumber),
      ].join(' '),
    );
    return searchable.contains(query);
  }

  @override
  Widget build(BuildContext context) {
    final visibleStudents = filteredStudents;
    final searchActive = normalizedQuery.isNotEmpty;
    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'Registered Students',
            subtitle:
                'Maintain student details, registered portraits, and exam eligibility.',
          ),
          const SectionTitle(
            title: 'Student Directory',
            subtitle:
                'Records are stored locally and remain available after closing the app.',
          ),
          if (widget.students.isNotEmpty) ...[
            TextField(
              controller: searchController,
              onChanged: (_) => setState(() {}),
              decoration: InputDecoration(
                labelText: 'Search student name or ID',
                prefixIcon: const Icon(Icons.search),
                suffixIcon: searchController.text.isEmpty
                    ? null
                    : IconButton(
                        tooltip: 'Clear search',
                        onPressed: () {
                          searchController.clear();
                          setState(() {});
                        },
                        icon: const Icon(Icons.close),
                      ),
              ),
            ),
            const SizedBox(height: 14),
            Text(
              searchActive
                  ? '${visibleStudents.length} matching student(s)'
                  : '${visibleStudents.length} registered student(s)',
              style: const TextStyle(color: AppColors.muted),
            ),
            const SizedBox(height: 12),
          ],
          if (widget.students.isEmpty)
            const EmptyState(message: 'No students registered yet.')
          else if (visibleStudents.isEmpty)
            EmptyState(
              message:
                  'No student matched "${searchController.text.trim()}". Check the spelling or student ID.',
            )
          else
            for (final student in visibleStudents)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: PanelCard(
                  borderColor: student.eligible
                      ? AppColors.green.withValues(alpha: 0.35)
                      : AppColors.red.withValues(alpha: 0.35),
                  child: Row(
                    children: [
                      Expanded(child: StudentInfoPane(student: student)),
                      const SizedBox(width: 12),
                      StatusPill(
                        label: student.eligible ? 'ELIGIBLE' : 'BLOCKED',
                        tone: student.eligible
                            ? AppColors.green
                            : AppColors.red,
                      ),
                      IconButton(
                        tooltip: 'Toggle eligibility',
                        onPressed: () => widget.onToggleEligibility(student),
                        icon: const Icon(Icons.swap_horiz),
                      ),
                      IconButton(
                        tooltip: 'Delete student record',
                        color: AppColors.red,
                        onPressed: () => _confirmDelete(context, student),
                        icon: const Icon(Icons.delete_outline),
                      ),
                    ],
                  ),
                ),
              ),
        ],
      ),
    );
  }

  Future<void> _confirmDelete(
    BuildContext context,
    StudentRecord student,
  ) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Delete student record?'),
        content: Text(
          '${student.fullName} will be removed from active biometric identification. This action cannot be undone.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.red),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;
    try {
      await widget.onDeleteStudent(student);
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${student.fullName} has been deleted.')),
      );
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not delete student: $error')),
      );
    }
  }
}

class EvaluationPage extends StatelessWidget {
  const EvaluationPage({
    required this.logs,
    required this.onResetMetrics,
    required this.onlineMode,
    super.key,
  });

  final List<VerificationRecord> logs;
  final Future<void> Function() onResetMetrics;
  final bool onlineMode;

  @override
  Widget build(BuildContext context) {
    final verified = logs
        .where((row) => row.status == VerificationStatus.verified)
        .length;
    final failed = logs
        .where((row) => row.status == VerificationStatus.notVerified)
        .length;
    final rate = logs.isEmpty ? 0 : (verified / logs.length * 100);

    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'System Evaluation',
            subtitle:
                'Review decision distribution before the recognition model is connected.',
          ),
          const SectionTitle(
            title: 'Evaluation Metrics',
            subtitle: 'Metrics based on the current verification records.',
          ),
          Align(
            alignment: Alignment.centerRight,
            child: OutlinedButton.icon(
              onPressed: logs.isEmpty
                  ? null
                  : () => _confirmResetMetrics(context),
              icon: const Icon(Icons.restart_alt_outlined),
              label: Text(
                onlineMode ? 'Reset shared metrics' : 'Reset local metrics',
              ),
            ),
          ),
          const SizedBox(height: 12),
          GridView.count(
            crossAxisCount: MediaQuery.sizeOf(context).width >= 720 ? 3 : 1,
            crossAxisSpacing: 14,
            mainAxisSpacing: 14,
            childAspectRatio: 2.2,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            children: [
              MetricCard(
                label: 'Attempts',
                value: '${logs.length}',
                accent: AppColors.sky,
              ),
              MetricCard(
                label: 'Verified',
                value: '$verified',
                accent: AppColors.green,
              ),
              MetricCard(
                label: 'Verification rate',
                value: '${rate.toStringAsFixed(1)}%',
                accent: failed == 0 ? AppColors.green : AppColors.red,
              ),
            ],
          ),
        ],
      ),
    );
  }

  Future<void> _confirmResetMetrics(BuildContext context) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Reset evaluation metrics?'),
        content: Text(
          onlineMode
              ? 'This will clear shared verification logs used for the evaluation metrics. Student records will not be deleted.'
              : 'This will clear local verification logs used for the evaluation metrics. Student records will not be deleted.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            style: FilledButton.styleFrom(backgroundColor: AppColors.red),
            onPressed: () => Navigator.of(dialogContext).pop(true),
            child: const Text('Reset metrics'),
          ),
        ],
      ),
    );
    if (confirmed != true || !context.mounted) return;
    try {
      await onResetMetrics();
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Evaluation metrics have been reset.')),
      );
    } catch (error) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('Could not reset metrics: $error')),
      );
    }
  }
}

class AdminRequestsPage extends StatefulWidget {
  const AdminRequestsPage({required this.client, super.key});

  final OnlineBackendClient? client;

  @override
  State<AdminRequestsPage> createState() => _AdminRequestsPageState();
}

class _AdminRequestsPageState extends State<AdminRequestsPage> {
  List<AdminAccessRequest> requests = const [];
  bool loading = false;
  String? message;
  Color messageColor = AppColors.green;

  @override
  void initState() {
    super.initState();
    _load();
  }

  Future<void> _load() async {
    final client = widget.client;
    if (client == null) {
      setState(() {
        requests = const [];
        message = 'Connect to the institutional network to review requests.';
        messageColor = AppColors.amber;
      });
      return;
    }
    setState(() {
      loading = true;
      message = null;
    });
    try {
      final loaded = await client.listAdminRequests();
      if (!mounted) return;
      setState(() => requests = loaded);
    } catch (_) {
      if (!mounted) return;
      setState(() {
        message = 'Access requests could not be loaded.';
        messageColor = AppColors.red;
      });
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> _decide(AdminAccessRequest request, String status) async {
    final client = widget.client;
    if (client == null) return;
    final temporaryPassword = status == 'approved'
        ? await _requestTemporaryPassword(request)
        : null;
    if (status == 'approved' && temporaryPassword == null) return;
    setState(() => loading = true);
    try {
      await client.decideAdminRequest(
        request.id,
        status,
        temporaryPassword: temporaryPassword,
      );
      await _load();
      if (!mounted) return;
      setState(() {
        message = status == 'approved'
            ? '${request.fullName} approved. Share the temporary password securely.'
            : '${request.fullName} rejected.';
        messageColor = status == 'approved' ? AppColors.green : AppColors.amber;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        message = 'The decision could not be saved.';
        messageColor = AppColors.red;
      });
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<String?> _requestTemporaryPassword(AdminAccessRequest request) async {
    final controller = TextEditingController();
    final password = await showDialog<String>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('Approve access request'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('Set a temporary password for ${request.fullName}.'),
            const SizedBox(height: 14),
            TextField(
              controller: controller,
              obscureText: true,
              autofocus: true,
              decoration: const InputDecoration(
                labelText: 'Temporary password',
                helperText: 'Minimum 8 characters',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(dialogContext).pop(),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () {
              final value = controller.text.trim();
              if (value.length >= 8) {
                Navigator.of(dialogContext).pop(value);
              }
            },
            child: const Text('Approve'),
          ),
        ],
      ),
    );
    controller.dispose();
    return password;
  }

  @override
  Widget build(BuildContext context) {
    final pending = requests.where((row) => row.status == 'pending').length;
    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'Access Requests',
            subtitle:
                'Review institutional account requests and approve authorized operators.',
          ),
          const SectionTitle(
            title: 'Approval Queue',
            subtitle:
                'Only Super Admin users can activate administrator and invigilator accounts.',
          ),
          GridView.count(
            crossAxisCount: MediaQuery.sizeOf(context).width >= 720 ? 3 : 1,
            crossAxisSpacing: 14,
            mainAxisSpacing: 14,
            childAspectRatio: 2.25,
            shrinkWrap: true,
            physics: const NeverScrollableScrollPhysics(),
            children: [
              MetricCard(
                label: 'Pending',
                value: '$pending',
                accent: AppColors.amber,
              ),
              MetricCard(
                label: 'Approved',
                value:
                    '${requests.where((row) => row.status == 'approved').length}',
                accent: AppColors.green,
              ),
              MetricCard(
                label: 'Rejected',
                value:
                    '${requests.where((row) => row.status == 'rejected').length}',
                accent: AppColors.red,
              ),
            ],
          ),
          const SizedBox(height: 14),
          if (message != null)
            InfoBanner(message: message!, color: messageColor),
          if (loading)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Center(
                child: CircularProgressIndicator(color: AppColors.cyan),
              ),
            )
          else if (requests.isEmpty)
            const EmptyState(message: 'No access requests are waiting.')
          else
            for (final request in requests)
              Padding(
                padding: const EdgeInsets.only(bottom: 10),
                child: PanelCard(
                  borderColor: request.statusColor.withValues(alpha: 0.34),
                  child: LayoutBuilder(
                    builder: (context, constraints) {
                      final compact = constraints.maxWidth < 720;
                      final details = Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            request.fullName,
                            style: const TextStyle(
                              color: Colors.white,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            '${request.email} / ${request.requestedRole}',
                            style: const TextStyle(color: AppColors.muted),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            [
                              if (request.department.isNotEmpty)
                                request.department,
                              _requestSubmittedLabel(request.createdAt),
                            ].join(' / '),
                            style: const TextStyle(
                              color: AppColors.muted,
                              fontSize: 12,
                            ),
                          ),
                          if (request.phoneNumber.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            Text(
                              request.phoneNumber,
                              style: const TextStyle(
                                color: AppColors.muted,
                                fontSize: 12,
                              ),
                            ),
                          ],
                          if (request.note.isNotEmpty) ...[
                            const SizedBox(height: 4),
                            Text(
                              request.note,
                              style: const TextStyle(
                                color: AppColors.muted,
                                fontSize: 12,
                              ),
                            ),
                          ],
                        ],
                      );
                      final actions = Wrap(
                        spacing: 10,
                        runSpacing: 8,
                        crossAxisAlignment: WrapCrossAlignment.center,
                        children: [
                          StatusPill(
                            label: request.status.toUpperCase(),
                            tone: request.statusColor,
                          ),
                          if (request.status == 'pending') ...[
                            OutlinedButton(
                              onPressed: loading
                                  ? null
                                  : () => _decide(request, 'rejected'),
                              child: const Text('Reject'),
                            ),
                            FilledButton(
                              onPressed: loading
                                  ? null
                                  : () => _decide(request, 'approved'),
                              child: const Text('Approve'),
                            ),
                          ],
                        ],
                      );
                      if (compact) {
                        return Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            details,
                            const SizedBox(height: 14),
                            actions,
                          ],
                        );
                      }
                      return Row(
                        children: [
                          Expanded(child: details),
                          const SizedBox(width: 16),
                          actions,
                        ],
                      );
                    },
                  ),
                ),
              ),
        ],
      ),
    );
  }

  String _requestSubmittedLabel(DateTime date) {
    final local = date.toLocal();
    final month = local.month.toString().padLeft(2, '0');
    final day = local.day.toString().padLeft(2, '0');
    final hour = local.hour.toString().padLeft(2, '0');
    final minute = local.minute.toString().padLeft(2, '0');
    return '${local.year}-$month-$day $hour:$minute';
  }
}

class LogsPage extends StatelessWidget {
  const LogsPage({required this.logs, super.key});

  final List<VerificationRecord> logs;

  @override
  Widget build(BuildContext context) {
    final audit = AuditSummary.fromLogs(logs);
    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'Verification Logs',
            subtitle:
                'Review captured attempts, outcomes, thresholds, and exported evidence.',
          ),
          const SectionTitle(
            title: 'Audit Trail',
            subtitle:
                'Verification records are protected with a tamper-evident audit chain.',
          ),
          if (audit.tampered > 0)
            InfoBanner(
              message:
                  'Audit integrity needs attention. ${audit.tampered} record(s) failed validation.',
              color: AppColors.red,
            )
          else if (audit.unsigned > 0)
            InfoBanner(
              message:
                  'Audit chain active. ${audit.checked} signed record(s), ${audit.unsigned} legacy unsigned record(s).',
              color: AppColors.amber,
            )
          else
            InfoBanner(
              message: 'Audit chain verified for ${audit.checked} record(s).',
              color: AppColors.green,
            ),
          const SizedBox(height: 12),
          if (logs.isEmpty)
            const EmptyState(message: 'No verification logs yet.')
          else
            for (final log in logs) VerificationLogCard(record: log),
        ],
      ),
    );
  }
}

class SideNavigation extends StatelessWidget {
  const SideNavigation({
    required this.navItems,
    required this.selectedIndex,
    required this.user,
    required this.onSelected,
    required this.onLogout,
    super.key,
  });

  final List<NavItem> navItems;
  final int selectedIndex;
  final AuthUser user;
  final ValueChanged<int> onSelected;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 292,
      decoration: const BoxDecoration(
        color: AppColors.sidebar,
        border: Border(right: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const BrandBlock(),
          UserPanel(user: user, onLogout: onLogout),
          Padding(
            padding: const EdgeInsets.fromLTRB(22, 22, 22, 8),
            child: Text(
              'NAVIGATION',
              style: Theme.of(context).textTheme.labelSmall?.copyWith(
                color: AppColors.muted,
                fontWeight: FontWeight.w800,
                letterSpacing: 1.1,
              ),
            ),
          ),
          Expanded(
            child: ListView.separated(
              padding: const EdgeInsets.symmetric(horizontal: 12),
              itemCount: navItems.length,
              separatorBuilder: (context, index) => const SizedBox(height: 5),
              itemBuilder: (context, index) {
                final item = navItems[index];
                final active = index == selectedIndex;
                return NavButton(
                  item: item,
                  active: active,
                  onTap: () => onSelected(index),
                );
              },
            ),
          ),
          const SizedBox(height: 12),
        ],
      ),
    );
  }
}

class MobileHeader extends StatelessWidget {
  const MobileHeader({
    required this.navItems,
    required this.selectedIndex,
    required this.user,
    required this.onSelected,
    required this.onLogout,
    super.key,
  });

  final List<NavItem> navItems;
  final int selectedIndex;
  final AuthUser user;
  final ValueChanged<int> onSelected;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 14, 16, 10),
      decoration: const BoxDecoration(
        color: AppColors.sidebar,
        border: Border(bottom: BorderSide(color: AppColors.border)),
      ),
      child: Column(
        children: [
          Row(
            children: [
              const BrandMark(),
              const SizedBox(width: 12),
              const Expanded(child: BrandText()),
              StatusPill(label: user.role, tone: AppColors.cyan),
              IconButton(
                tooltip: 'Sign out',
                onPressed: onLogout,
                icon: const Icon(Icons.logout, color: AppColors.soft),
              ),
            ],
          ),
          const SizedBox(height: 12),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              children: [
                for (var i = 0; i < navItems.length; i++)
                  Padding(
                    padding: const EdgeInsets.only(right: 8),
                    child: FilterChip(
                      selected: i == selectedIndex,
                      showCheckmark: false,
                      label: Text(navItems[i].label),
                      avatar: Icon(navItems[i].icon, size: 16),
                      onSelected: (_) => onSelected(i),
                    ),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class BrandBlock extends StatelessWidget {
  const BrandBlock({super.key});

  @override
  Widget build(BuildContext context) {
    return const Padding(
      padding: EdgeInsets.fromLTRB(20, 22, 20, 18),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              BrandMark(),
              SizedBox(width: 12),
              Expanded(child: BrandText()),
            ],
          ),
          SizedBox(height: 16),
          Row(
            children: [StatusPill(label: 'v1.0', tone: AppColors.cyan)],
          ),
        ],
      ),
    );
  }
}

class UserPanel extends StatelessWidget {
  const UserPanel({required this.user, required this.onLogout, super.key});

  final AuthUser user;
  final VoidCallback onLogout;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 4),
      child: Container(
        width: double.infinity,
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.panelWeak,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.border),
        ),
        child: Row(
          children: [
            const Icon(
              Icons.admin_panel_settings_outlined,
              color: AppColors.cyan,
            ),
            const SizedBox(width: 10),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    user.fullName,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      color: Colors.white,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    '${user.role} access',
                    style: const TextStyle(
                      color: AppColors.muted,
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
            ),
            IconButton(
              tooltip: 'Sign out',
              onPressed: onLogout,
              icon: const Icon(Icons.logout, color: AppColors.soft),
            ),
          ],
        ),
      ),
    );
  }
}

class BrandMark extends StatelessWidget {
  const BrandMark({super.key});

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: Container(
        width: 48,
        height: 48,
        decoration: BoxDecoration(
          color: const Color(0xFF071327),
          boxShadow: [
            BoxShadow(
              color: AppColors.cyan.withValues(alpha: 0.16),
              blurRadius: 18,
            ),
          ],
        ),
        child: Image.asset(
          'assets/brand/examverify_logo_512.png',
          fit: BoxFit.cover,
        ),
      ),
    );
  }
}

class BrandText extends StatelessWidget {
  const BrandText({super.key});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'ExamVerify',
          style: Theme.of(context).textTheme.titleMedium?.copyWith(
            color: Colors.white,
            fontWeight: FontWeight.w900,
          ),
        ),
        const SizedBox(height: 2),
        Text(
          'Exam Authentication System',
          style: Theme.of(context).textTheme.labelMedium?.copyWith(
            color: AppColors.muted,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    );
  }
}

class NavButton extends StatelessWidget {
  const NavButton({
    required this.item,
    required this.active,
    required this.onTap,
    super.key,
  });

  final NavItem item;
  final bool active;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.transparent,
      child: InkWell(
        borderRadius: BorderRadius.circular(10),
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 160),
          constraints: const BoxConstraints(minHeight: 46),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
          decoration: BoxDecoration(
            color: active ? AppColors.activeNav : Colors.transparent,
            borderRadius: BorderRadius.circular(10),
            border: Border.all(
              color: active ? AppColors.cyanSoft : Colors.transparent,
            ),
          ),
          child: Row(
            children: [
              Icon(
                item.icon,
                size: 20,
                color: active ? AppColors.cyan : AppColors.soft,
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  item.label,
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: active ? Colors.white : AppColors.soft,
                    fontWeight: active ? FontWeight.w800 : FontWeight.w600,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _ExamSessionSelector extends StatelessWidget {
  const _ExamSessionSelector({
    required this.sessions,
    required this.selected,
    required this.onChanged,
  });

  final List<ExamSessionRecord> sessions;
  final ExamSessionRecord? selected;
  final ValueChanged<ExamSessionRecord?> onChanged;

  @override
  Widget build(BuildContext context) {
    return DropdownButtonFormField<ExamSessionRecord>(
      initialValue: selected,
      decoration: const InputDecoration(labelText: 'Active exam session'),
      items: [
        for (final session in sessions)
          DropdownMenuItem(value: session, child: Text(session.label)),
      ],
      onChanged: onChanged,
    );
  }
}

class ExamSessionsPage extends StatefulWidget {
  const ExamSessionsPage({
    required this.students,
    required this.sessions,
    required this.client,
    required this.onChanged,
    super.key,
  });

  final List<StudentRecord> students;
  final List<ExamSessionRecord> sessions;
  final OnlineBackendClient? client;
  final Future<void> Function() onChanged;

  @override
  State<ExamSessionsPage> createState() => _ExamSessionsPageState();
}

class _ExamSessionsPageState extends State<ExamSessionsPage> {
  final code = TextEditingController();
  final name = TextEditingController();
  final program = TextEditingController();
  final level = TextEditingController();
  final date = TextEditingController();
  final venue = TextEditingController();
  String? message;
  bool busy = false;

  @override
  void dispose() {
    code.dispose();
    name.dispose();
    program.dispose();
    level.dispose();
    date.dispose();
    venue.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AppScrollView(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const PageHero(
            title: 'Exam Sessions',
            subtitle:
                'Authorize already-enrolled students for a specific examination.',
          ),
          if (widget.client == null)
            const EmptyState(
              message:
                  'Connect to the cloud backend to create and manage exam sessions.',
            )
          else ...[
            PanelCard(
              child: Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  SizedBox(
                    width: 180,
                    child: TextField(
                      controller: code,
                      decoration: const InputDecoration(
                        labelText: 'Course code',
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 260,
                    child: TextField(
                      controller: name,
                      decoration: const InputDecoration(
                        labelText: 'Course name',
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 180,
                    child: TextField(
                      controller: program,
                      decoration: const InputDecoration(labelText: 'Program'),
                    ),
                  ),
                  SizedBox(
                    width: 140,
                    child: TextField(
                      controller: level,
                      decoration: const InputDecoration(labelText: 'Level'),
                    ),
                  ),
                  SizedBox(
                    width: 180,
                    child: TextField(
                      controller: date,
                      decoration: const InputDecoration(
                        labelText: 'Exam date YYYY-MM-DD',
                      ),
                    ),
                  ),
                  SizedBox(
                    width: 220,
                    child: TextField(
                      controller: venue,
                      decoration: const InputDecoration(labelText: 'Venue'),
                    ),
                  ),
                  FilledButton.icon(
                    onPressed: busy ? null : _create,
                    icon: const Icon(Icons.add),
                    label: const Text('Create session'),
                  ),
                ],
              ),
            ),
            if (message != null) ...[
              const SizedBox(height: 12),
              Text(message!, style: const TextStyle(color: AppColors.muted)),
            ],
            const SizedBox(height: 18),
            for (final session in widget.sessions)
              Padding(
                padding: const EdgeInsets.only(bottom: 12),
                child: PanelCard(
                  child: Row(
                    children: [
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              session.label,
                              style: const TextStyle(
                                color: Colors.white,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                            Text(
                              '${session.program} Level ${session.level} | ${session.examDate} | ${session.status}',
                              style: const TextStyle(color: AppColors.muted),
                            ),
                          ],
                        ),
                      ),
                      OutlinedButton(
                        onPressed: () => _addStudent(session),
                        child: const Text('Add student'),
                      ),
                      const SizedBox(width: 8),
                      FilledButton(
                        onPressed: () => _activate(session),
                        child: Text(session.isActive ? 'Active' : 'Activate'),
                      ),
                      const SizedBox(width: 8),
                      OutlinedButton(
                        onPressed: () => _complete(session),
                        child: const Text('Complete'),
                      ),
                    ],
                  ),
                ),
              ),
          ],
        ],
      ),
    );
  }

  Future<void> _create() async {
    setState(() => busy = true);
    try {
      await widget.client!.createExamSession(
        courseCode: code.text.trim(),
        courseName: name.text.trim(),
        program: program.text.trim(),
        level: level.text.trim(),
        examDate: date.text.trim(),
        startTime: '',
        endTime: '',
        venue: venue.text.trim(),
      );
      await widget.onChanged();
    } catch (error) {
      if (mounted) setState(() => message = error.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> _activate(ExamSessionRecord session) async {
    await widget.client!.activateExamSession(session.id);
    await widget.onChanged();
  }

  Future<void> _complete(ExamSessionRecord session) async {
    await widget.client!.completeExamSession(session.id);
    await widget.onChanged();
  }

  Future<void> _addStudent(ExamSessionRecord session) async {
    StudentRecord? student = widget.students.firstOrNull;
    var eligibilityType = 'regular';
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, setDialogState) => AlertDialog(
          title: Text('Add student to ${session.courseCode}'),
          content: SizedBox(
            width: 460,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                DropdownButtonFormField<StudentRecord>(
                  initialValue: student,
                  decoration: const InputDecoration(labelText: 'Student'),
                  items: [
                    for (final row in widget.students)
                      DropdownMenuItem(
                        value: row,
                        child: Text('${row.studentNumber} - ${row.fullName}'),
                      ),
                  ],
                  onChanged: (value) => setDialogState(() => student = value),
                ),
                const SizedBox(height: 14),
                DropdownButtonFormField<String>(
                  initialValue: eligibilityType,
                  decoration: const InputDecoration(
                    labelText: 'Eligibility type',
                  ),
                  items: [
                    for (final type in const [
                      'regular',
                      'repeat',
                      'deferred',
                      'supplementary',
                      'manual_override',
                    ])
                      DropdownMenuItem(value: type, child: Text(type)),
                  ],
                  onChanged: (value) => setDialogState(
                    () => eligibilityType = value ?? 'regular',
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const Text('Cancel'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(context, true),
              child: const Text('Add eligible student'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true || student?.id == null) return;
    await widget.client!.addExamEligibility(
      sessionId: session.id,
      studentId: student!.id!,
      eligibilityType: eligibilityType,
    );
    await widget.onChanged();
  }
}

class StudentInfoPane extends StatelessWidget {
  const StudentInfoPane({required this.student, super.key});

  final StudentRecord student;

  @override
  Widget build(BuildContext context) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact = constraints.maxWidth < 420;
        final portrait = ClipRRect(
          borderRadius: BorderRadius.circular(16),
          child: Container(
            width: compact ? double.infinity : 92,
            height: compact ? 180 : 104,
            decoration: BoxDecoration(
              color: const Color(0xFF071327),
              border: Border.all(color: AppColors.border),
            ),
            child: student.photoPath.isEmpty
                ? const Icon(Icons.badge_outlined, color: AppColors.muted)
                : _StoredPortrait(path: student.photoPath),
          ),
        );
        final details = Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              student.fullName,
              style: const TextStyle(
                color: Colors.white,
                fontSize: 16,
                fontWeight: FontWeight.w900,
              ),
            ),
            const SizedBox(height: 10),
            _StudentInfoLine(
              label: 'Student ID',
              value: AuthService.maskIdentifier(student.studentNumber),
            ),
            _StudentInfoLine(
              label: 'Program',
              value: student.program.isEmpty
                  ? 'Program not recorded'
                  : student.program,
            ),
            _StudentInfoLine(
              label: 'Eligibility',
              value: student.eligible ? 'Eligible' : 'Blocked',
              valueColor: student.eligible ? AppColors.green : AppColors.red,
            ),
            if (student.note.isNotEmpty)
              _StudentInfoLine(label: 'Note', value: student.note),
          ],
        );
        if (compact) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [portrait, const SizedBox(height: 12), details],
          );
        }
        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            portrait,
            const SizedBox(width: 14),
            Expanded(child: details),
          ],
        );
      },
    );
  }
}

class _StudentInfoLine extends StatelessWidget {
  const _StudentInfoLine({
    required this.label,
    required this.value,
    this.valueColor,
  });

  final String label;
  final String value;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 5),
      child: RichText(
        text: TextSpan(
          style: const TextStyle(color: AppColors.muted, fontSize: 12),
          children: [
            TextSpan(
              text: '$label: ',
              style: const TextStyle(fontWeight: FontWeight.w900),
            ),
            TextSpan(
              text: value,
              style: TextStyle(
                color: valueColor ?? AppColors.soft,
                fontWeight: FontWeight.w700,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class StudentSummary extends StatelessWidget {
  const StudentSummary({required this.student, super.key});

  final StudentRecord student;

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          student.fullName,
          style: const TextStyle(
            color: Colors.white,
            fontWeight: FontWeight.w900,
          ),
        ),
        const SizedBox(height: 3),
        Text(
          '${student.studentNumber} • ${student.program.isEmpty ? 'Program not recorded' : student.program}',
          style: const TextStyle(color: AppColors.muted, fontSize: 12),
        ),
        if (student.note.isNotEmpty) ...[
          const SizedBox(height: 3),
          Text(
            student.note,
            style: const TextStyle(color: AppColors.soft, fontSize: 12),
          ),
        ],
      ],
    );
  }
}

class AutoIdentifyResultPanel extends StatelessWidget {
  const AutoIdentifyResultPanel({
    required this.student,
    required this.status,
    required this.score,
    required this.imageFile,
    super.key,
  });

  final StudentRecord? student;
  final VerificationStatus status;
  final double score;
  final File? imageFile;

  @override
  Widget build(BuildContext context) {
    final verified = status == VerificationStatus.verified;
    final spoof = status == VerificationStatus.spoofDetected;
    final accent = verified
        ? AppColors.green
        : spoof
        ? AppColors.amber
        : AppColors.red;
    final confidence = verified
        ? ((1 - (score / FaceEngine.identificationThreshold)) * 100)
              .clamp(72, 99)
              .round()
        : ((1 - score.clamp(0.0, 1.0)) * 100).clamp(0, 68).round();
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: accent.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: accent.withValues(alpha: 0.45)),
        boxShadow: [
          BoxShadow(
            color: accent.withValues(alpha: 0.12),
            blurRadius: 28,
            offset: const Offset(0, 14),
          ),
        ],
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 560;
          final image = ClipRRect(
            borderRadius: BorderRadius.circular(14),
            child: Container(
              width: compact ? double.infinity : 112,
              height: compact ? 180 : 112,
              color: const Color(0xFF071327),
              child: student != null
                  ? _StoredPortrait(path: student!.photoPath)
                  : imageFile != null
                  ? Image.file(imageFile!, fit: BoxFit.cover)
                  : const Icon(
                      Icons.person_off_outlined,
                      color: AppColors.muted,
                    ),
            ),
          );
          final details = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _SignalChip(label: status.label.toUpperCase(), color: accent),
              const SizedBox(height: 10),
              Text(
                student?.fullName ??
                    (spoof ? 'Spoof attempt detected' : 'Unauthorized face'),
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 20,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 6),
              Text(
                student == null
                    ? 'No trusted student profile matched.'
                    : '${student!.studentNumber} • ${student!.program.isEmpty ? 'Program not recorded' : student!.program}',
                style: const TextStyle(color: AppColors.soft),
              ),
              const SizedBox(height: 12),
              Row(
                children: [
                  Expanded(
                    child: ClipRRect(
                      borderRadius: BorderRadius.circular(999),
                      child: LinearProgressIndicator(
                        value: confidence / 100,
                        minHeight: 8,
                        backgroundColor: Colors.white.withValues(alpha: 0.08),
                        color: accent,
                      ),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Text(
                    '$confidence%',
                    style: TextStyle(
                      color: accent,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ],
              ),
            ],
          );
          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [image, const SizedBox(height: 14), details],
            );
          }
          return Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              image,
              const SizedBox(width: 16),
              Expanded(child: details),
            ],
          );
        },
      ),
    );
  }
}

class _StoredPortrait extends StatelessWidget {
  const _StoredPortrait({required this.path});

  final String path;

  @override
  Widget build(BuildContext context) {
    if (path.startsWith('data:image/')) {
      try {
        final separator = path.indexOf(',');
        if (separator > 0) {
          return Image.memory(
            base64Decode(path.substring(separator + 1)),
            fit: BoxFit.cover,
            errorBuilder: (context, error, stackTrace) => _fallback(),
          );
        }
      } catch (_) {
        return _fallback();
      }
    }
    if (path.startsWith('http://') || path.startsWith('https://')) {
      return Image.network(
        path,
        fit: BoxFit.cover,
        errorBuilder: (context, error, stackTrace) => _fallback(),
      );
    }
    final file = File(path);
    if (path.isNotEmpty && file.existsSync()) {
      return Image.file(
        file,
        fit: BoxFit.cover,
        errorBuilder: (context, error, stackTrace) => _fallback(),
      );
    }
    return _fallback();
  }

  Widget _fallback() =>
      const Icon(Icons.account_circle_outlined, color: AppColors.muted);
}

class ImageCapturePanel extends StatelessWidget {
  const ImageCapturePanel({
    required this.title,
    required this.subtitle,
    required this.imageFile,
    this.onCamera,
    this.cameraLabel = 'Camera',
    super.key,
  });

  final String title;
  final String subtitle;
  final File? imageFile;
  final VoidCallback? onCamera;
  final String cameraLabel;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: AppColors.panelWeak,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: AppColors.border),
      ),
      child: LayoutBuilder(
        builder: (context, constraints) {
          final compact = constraints.maxWidth < 560;
          final preview = ClipRRect(
            borderRadius: BorderRadius.circular(10),
            child: Container(
              height: 132,
              width: compact ? double.infinity : 132,
              color: const Color(0xFF071327),
              child: imageFile == null
                  ? const Icon(
                      Icons.face_retouching_natural_outlined,
                      color: AppColors.cyan,
                      size: 42,
                    )
                  : Image.file(imageFile!, fit: BoxFit.cover),
            ),
          );
          final controls = Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  color: Colors.white,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 4),
              Text(
                subtitle,
                style: const TextStyle(color: AppColors.muted, fontSize: 12),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 10,
                runSpacing: 10,
                children: [
                  if (onCamera != null)
                    FilledButton.icon(
                      onPressed: onCamera,
                      icon: const Icon(Icons.photo_camera_outlined),
                      label: Text(cameraLabel),
                    ),
                ],
              ),
            ],
          );

          if (compact) {
            return Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [preview, const SizedBox(height: 12), controls],
            );
          }
          return Row(
            children: [
              preview,
              const SizedBox(width: 14),
              Expanded(child: controls),
            ],
          );
        },
      ),
    );
  }
}

enum BiometricScanMode { enrollment, portrait, verification, autoIdentify }

enum _BiometricCameraState {
  initializing,
  ready,
  liveness,
  portraitCapture,
  processing,
  complete,
  error,
}

enum _BiometricChallengeType {
  centerInitial,
  lookLeft,
  lookRight,
  lookUp,
  tilt,
  blink,
  centerFinal,
}

class _BiometricChallenge {
  const _BiometricChallenge(this.type, this.label, this.detail);

  final _BiometricChallengeType type;
  final String label;
  final String detail;
}

class FaceSignal {
  const FaceSignal({
    required this.faceCount,
    required this.quality,
    required this.yaw,
    required this.pitch,
    required this.roll,
    required this.leftEyeOpen,
    required this.rightEyeOpen,
    required this.poseReliable,
    required this.message,
  });

  final int faceCount;
  final double quality;
  final double yaw;
  final double pitch;
  final double roll;
  final double leftEyeOpen;
  final double rightEyeOpen;
  final bool poseReliable;
  final String message;

  bool get facePresent => faceCount == 1;
  bool get eyesClosed => ((leftEyeOpen + rightEyeOpen) / 2) < 0.46;
  bool get eyesOpen => ((leftEyeOpen + rightEyeOpen) / 2) > 0.50;
}

Future<File?> showBiometricScanner(
  BuildContext context, {
  required BiometricScanMode mode,
}) {
  return Navigator.of(context).push<File>(
    MaterialPageRoute(
      fullscreenDialog: true,
      builder: (context) => BiometricScannerScreen(mode: mode),
    ),
  );
}

Future<File?> showCameraCaptureDialog(BuildContext context) {
  return showDialog<File>(
    context: context,
    barrierDismissible: false,
    builder: (context) => const CameraCaptureDialog(),
  );
}

class BiometricScannerScreen extends StatefulWidget {
  const BiometricScannerScreen({required this.mode, super.key});

  final BiometricScanMode mode;

  @override
  State<BiometricScannerScreen> createState() => _BiometricScannerScreenState();
}

class _BiometricScannerScreenState extends State<BiometricScannerScreen>
    with SingleTickerProviderStateMixin {
  camera.CameraController? controller;
  List<camera.CameraDescription> availableDeviceCameras = const [];
  camera.CameraLensDirection selectedLens = camera.CameraLensDirection.front;
  late final AnimationController animation;
  late List<_BiometricChallenge> challenges;
  Timer? analysisTimer;
  Timer? portraitCaptureTimer;
  int challengeIndex = 0;
  int blinkCount = 0;
  int blinkFallbackFrames = 0;
  int challengeStableFrames = 0;
  static const double minimumPortraitQuality = 0.64;
  static const double minimumDesktopScanQuality = 0.62;
  static const double minimumMobileScanQuality = 0.50;
  final List<String> completedChallengeLabels = [];
  bool wasClosed = false;
  bool analyzing = false;
  bool completing = false;
  bool portraitCapturePending = false;
  bool returnedFrame = false;
  bool previewReady = false;
  _BiometricCameraState cameraState = _BiometricCameraState.initializing;
  DateTime lastUiUpdate = DateTime.fromMillisecondsSinceEpoch(0);
  DateTime challengeStartedAt = DateTime.now();
  DateTime? portraitLockedAt;
  String message = 'Initializing secure camera...';
  FaceSignal? signal;
  FaceSignal? centeredBaseline;
  File? bestFrame;
  double bestFrameScore = 0;

  @override
  void initState() {
    super.initState();
    challenges = _buildChallenges(widget.mode);
    animation = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 3),
    )..repeat();
    _openCamera();
  }

  @override
  void dispose() {
    analysisTimer?.cancel();
    portraitCaptureTimer?.cancel();
    controller?.dispose();
    animation.dispose();
    if (!returnedFrame) {
      final frame = bestFrame;
      if (frame != null) unawaited(frame.delete().catchError((_) => frame));
    }
    super.dispose();
  }

  List<_BiometricChallenge> _buildChallenges(BiometricScanMode mode) {
    const center = _BiometricChallenge(
      _BiometricChallengeType.centerInitial,
      'Center Face',
      'Align your face and hold still until quality is safe for matching.',
    );
    const blink = _BiometricChallenge(
      _BiometricChallengeType.blink,
      'Blink Eyes',
      'Blink your eyes naturally.',
    );
    const desktopBlink = _BiometricChallenge(
      _BiometricChallengeType.blink,
      'Blink Eyes',
      'Close your eyes briefly, then open them.',
    );
    const left = _BiometricChallenge(
      _BiometricChallengeType.lookLeft,
      'Turn Left',
      'Slowly turn your head to the left.',
    );
    const right = _BiometricChallenge(
      _BiometricChallengeType.lookRight,
      'Turn Right',
      'Now turn your head to the right.',
    );
    const up = _BiometricChallenge(
      _BiometricChallengeType.lookUp,
      'Look Slightly Up',
      'Slightly look upwards.',
    );
    return switch (mode) {
      BiometricScanMode.enrollment when Platform.isWindows => [
        center,
        left,
        right,
        desktopBlink,
      ],
      BiometricScanMode.enrollment => [center, left, right, up, blink],
      BiometricScanMode.portrait => [
        const _BiometricChallenge(
          _BiometricChallengeType.centerFinal,
          'Final Portrait Alignment',
          'Perfect! Center your face and look at the camera.',
        ),
      ],
      BiometricScanMode.verification when Platform.isWindows => [
        center,
        desktopBlink,
      ],
      BiometricScanMode.autoIdentify when Platform.isWindows => [
        center,
        desktopBlink,
      ],
      BiometricScanMode.verification => [center, blink],
      BiometricScanMode.autoIdentify => [center, blink],
    };
  }

  Future<void> _openCamera() async {
    try {
      final previousController = controller;
      controller = null;
      analysisTimer?.cancel();
      portraitCaptureTimer?.cancel();
      if (previousController != null) {
        await previousController.dispose();
      }
      if (!mounted) return;
      setState(() {
        cameraState = _BiometricCameraState.initializing;
        previewReady = false;
        message = 'Initializing secure camera...';
      });
      if ((Platform.isAndroid || Platform.isIOS)) {
        final status = await Permission.camera.request();
        if (!status.isGranted) {
          setState(() {
            cameraState = _BiometricCameraState.error;
            message = 'Camera permission is required.';
          });
          return;
        }
      }
      final cameras = await camera.availableCameras();
      if (cameras.isEmpty) {
        setState(() {
          cameraState = _BiometricCameraState.error;
          message = 'No camera was found on this device.';
        });
        return;
      }
      availableDeviceCameras = cameras;
      final selected = cameras.firstWhere(
        (item) => item.lensDirection == selectedLens,
        orElse: () => cameras.first,
      );
      selectedLens = selected.lensDirection;
      final nextController = camera.CameraController(
        selected,
        Platform.isAndroid || Platform.isIOS
            ? camera.ResolutionPreset.low
            : camera.ResolutionPreset.high,
        enableAudio: false,
      );
      await nextController.initialize();
      if (!mounted) {
        await nextController.dispose();
        return;
      }
      setState(() {
        controller = nextController;
        cameraState = _BiometricCameraState.ready;
        message = 'Preparing scanner preview...';
      });
      WidgetsBinding.instance.addPostFrameCallback((_) {
        Future<void>.delayed(const Duration(milliseconds: 650), () {
          if (!mounted || controller != nextController || completing) return;
          setState(() {
            previewReady = true;
            cameraState = _activeScanState;
            challengeStartedAt = DateTime.now();
            message = challenges.first.detail;
          });
          _startAnalysisTimer();
        });
      });
    } catch (error) {
      if (!mounted) return;
      debugPrint('ExamVerify camera initialization failed: $error');
      setState(() {
        cameraState = _BiometricCameraState.error;
        message = 'Camera initialization failed. Please retry.';
      });
    }
  }

  _BiometricCameraState get _activeScanState {
    if (widget.mode == BiometricScanMode.portrait ||
        cameraState == _BiometricCameraState.portraitCapture) {
      return _BiometricCameraState.portraitCapture;
    }
    return _BiometricCameraState.liveness;
  }

  bool get _cameraReady {
    final active = controller;
    return active != null && active.value.isInitialized && previewReady;
  }

  bool get _canSwitchMobileCamera {
    if (!Platform.isAndroid && !Platform.isIOS) return false;
    return availableDeviceCameras.any(
          (item) => item.lensDirection == camera.CameraLensDirection.front,
        ) &&
        availableDeviceCameras.any(
          (item) => item.lensDirection == camera.CameraLensDirection.back,
        );
  }

  Future<void> _switchMobileCamera() async {
    if (!_canSwitchMobileCamera || analyzing || completing) return;
    analysisTimer?.cancel();
    portraitCaptureTimer?.cancel();
    final previousController = controller;
    controller = null;
    previewReady = false;
    selectedLens = selectedLens == camera.CameraLensDirection.front
        ? camera.CameraLensDirection.back
        : camera.CameraLensDirection.front;
    if (mounted) {
      setState(() {
        cameraState = _BiometricCameraState.initializing;
        message = 'Switching camera...';
        signal = null;
      });
    }
    await previousController?.dispose();
    if (mounted) await _openCamera();
  }

  void _startAnalysisTimer({Duration? interval}) {
    analysisTimer?.cancel();
    analysisTimer = Timer.periodic(
      interval ??
          (Platform.isWindows
              ? const Duration(milliseconds: 450)
              : const Duration(milliseconds: 1250)),
      (_) => _analyzeFrame(),
    );
  }

  Future<void> _analyzeFrame() async {
    final active = controller;
    if (active == null ||
        !active.value.isInitialized ||
        !previewReady ||
        cameraState == _BiometricCameraState.initializing ||
        cameraState == _BiometricCameraState.error ||
        cameraState == _BiometricCameraState.complete ||
        active.value.isTakingPicture ||
        analyzing ||
        portraitCapturePending ||
        completing) {
      return;
    }
    analyzing = true;
    final previousState = cameraState;
    cameraState = _BiometricCameraState.processing;
    try {
      final image = await active.takePicture();
      final frame = File(image.path);
      final nextSignal = await FaceEngine.analyzeFaceSignal(frame);
      if (!mounted) return;
      final challenge = challenges[challengeIndex];
      final passed = _passesChallenge(challenge, nextSignal);
      _updateScannerState(nextSignal, passed, frame);
      if (passed) {
        await Future<void>.delayed(const Duration(milliseconds: 360));
        if (!mounted) return;
        if (challengeIndex < challenges.length - 1) {
          _advanceChallenge(nextSignal);
        } else if (widget.mode == BiometricScanMode.enrollment &&
            previousState != _BiometricCameraState.portraitCapture) {
          _rememberCompletedChallenge(challenge);
          _enterPortraitMode(frame);
        } else {
          _rememberCompletedChallenge(challenge);
          await _completeScan(frame);
        }
      } else if (bestFrame?.path != frame.path) {
        unawaited(frame.delete().catchError((_) => File(frame.path)));
      }
    } catch (error) {
      debugPrint('ExamVerify scan frame failed: $error');
      if (mounted) {
        setState(() {
          message = 'Camera signal interrupted. Hold steady and retry.';
          cameraState = _activeScanState;
        });
      }
    } finally {
      if (!completing &&
          mounted &&
          cameraState == _BiometricCameraState.processing) {
        cameraState = _activeScanState;
      }
      analyzing = false;
    }
  }

  bool _passesChallenge(_BiometricChallenge challenge, FaceSignal nextSignal) {
    if (!nextSignal.facePresent || nextSignal.quality < 0.16) return false;
    switch (challenge.type) {
      case _BiometricChallengeType.centerInitial:
        final isDesktop = Platform.isWindows;
        final minQuality = isDesktop
            ? minimumDesktopScanQuality
            : minimumMobileScanQuality;
        final centered =
            nextSignal.yaw.abs() < (isDesktop ? 14.0 : 8.0) &&
            nextSignal.pitch.abs() < (isDesktop ? 14.0 : 8.0) &&
            nextSignal.roll.abs() < (isDesktop ? 14.0 : 10.0) &&
            nextSignal.quality >= minQuality &&
            (isDesktop ? nextSignal.poseReliable : true);
        final frames = switch (widget.mode) {
          BiometricScanMode.verification => isDesktop ? 4 : 3,
          BiometricScanMode.autoIdentify => isDesktop ? 4 : 3,
          BiometricScanMode.enrollment => isDesktop ? 3 : 3,
          BiometricScanMode.portrait => 3,
        };
        return _stableChallenge(centered, requiredFrames: frames);
      case _BiometricChallengeType.lookLeft:
        return _stableChallenge(nextSignal.yaw > 11.0, requiredFrames: 2);
      case _BiometricChallengeType.lookRight:
        return _stableChallenge(nextSignal.yaw < -11.0, requiredFrames: 2);
      case _BiometricChallengeType.lookUp:
        return _stableChallenge(nextSignal.pitch > 9.0, requiredFrames: 2);
      case _BiometricChallengeType.tilt:
        return _stableChallenge(nextSignal.roll.abs() >= 8, requiredFrames: 2);
      case _BiometricChallengeType.blink:
        final eyeOpen = _averageEyeOpen(nextSignal);
        final desktopBaseline = centeredBaseline == null
            ? 0.65
            : _averageEyeOpen(centeredBaseline!);
        final eyesClosed = Platform.isWindows
            ? eyeOpen < math.min(0.62, desktopBaseline * 0.78)
            : nextSignal.eyesClosed;
        final eyesOpen = Platform.isWindows
            ? eyeOpen > math.max(0.30, desktopBaseline * 0.68)
            : nextSignal.eyesOpen;
        if (Platform.isWindows &&
            nextSignal.quality < minimumDesktopScanQuality - 0.12) {
          wasClosed = false;
          blinkFallbackFrames = 0;
          return false;
        }
        if (eyesClosed && !wasClosed) {
          wasClosed = true;
          blinkFallbackFrames = 0;
        }
        if (wasClosed && eyesOpen) {
          blinkCount++;
          wasClosed = false;
          return true;
        }
        if (Platform.isWindows &&
            widget.mode != BiometricScanMode.verification &&
            nextSignal.quality >= minimumDesktopScanQuality &&
            nextSignal.facePresent &&
            nextSignal.poseReliable) {
          blinkFallbackFrames++;
          if (blinkFallbackFrames >= 12) {
            blinkCount = 1;
            return true;
          }
        } else {
          blinkFallbackFrames = 0;
        }
        return false;
      case _BiometricChallengeType.centerFinal:
        final isDesktop = Platform.isWindows;
        final stable =
            nextSignal.yaw.abs() < (isDesktop ? 12.0 : 6.0) &&
            nextSignal.pitch.abs() < (isDesktop ? 12.0 : 6.0) &&
            nextSignal.roll.abs() < (isDesktop ? 12.0 : 8.0) &&
            (isDesktop
                ? _averageEyeOpen(nextSignal) > 0.35
                : nextSignal.eyesOpen) &&
            nextSignal.quality >= minimumPortraitQuality;
        if (!stable) {
          portraitLockedAt = null;
          return false;
        }
        portraitLockedAt ??= DateTime.now();
        return false;
    }
  }

  bool _stableChallenge(bool condition, {int requiredFrames = 2}) {
    challengeStableFrames = condition ? challengeStableFrames + 1 : 0;
    return challengeStableFrames >= requiredFrames;
  }

  void _rememberCompletedChallenge(_BiometricChallenge challenge) {
    if (!completedChallengeLabels.contains(challenge.label)) {
      completedChallengeLabels.add(challenge.label);
    }
  }

  void _advanceChallenge(FaceSignal nextSignal) {
    final current = challenges[challengeIndex];
    setState(() {
      _rememberCompletedChallenge(current);
      if (current.type == _BiometricChallengeType.centerInitial ||
          centeredBaseline == null) {
        centeredBaseline = nextSignal;
      }
      challengeIndex++;
      blinkCount = 0;
      blinkFallbackFrames = 0;
      wasClosed = false;
      challengeStableFrames = 0;
      challengeStartedAt = DateTime.now();
      message = challenges[challengeIndex].detail;
      cameraState = _activeScanState;
    });
    if (challenges[challengeIndex].type == _BiometricChallengeType.blink &&
        (Platform.isAndroid || Platform.isIOS || Platform.isWindows)) {
      _startAnalysisTimer(
        interval: Platform.isWindows
            ? const Duration(milliseconds: 220)
            : const Duration(milliseconds: 380),
      );
    }
  }

  void _updateScannerState(FaceSignal nextSignal, bool passed, File frame) {
    final portraitMode =
        challenges[challengeIndex].type == _BiometricChallengeType.centerFinal;
    final portraitHoldMessage = portraitLockedAt == null
        ? 'Center your face in the best available light. Quality must be stable.'
        : Platform.isWindows
        ? 'Face locked. Capturing in a moment.'
        : 'Face locked. Hold still for 2 seconds.';
    final nextMessage = passed
        ? portraitMode
              ? 'Portrait quality locked. Capturing image...'
              : 'Confirmed: ${challenges[challengeIndex].label} detected'
        : nextSignal.facePresent
        ? portraitMode
              ? portraitHoldMessage
              : challenges[challengeIndex].detail
        : nextSignal.message;
    final now = DateTime.now();
    final shouldUpdate =
        nextMessage != message ||
        signal?.facePresent != nextSignal.facePresent ||
        now.difference(lastUiUpdate).inMilliseconds > 900;
    final canSelectFrame = Platform.isWindows
        ? nextSignal.quality >= minimumDesktopScanQuality
        : portraitMode
        ? nextSignal.quality >= minimumPortraitQuality
        : nextSignal.quality >= minimumMobileScanQuality;
    if (nextSignal.facePresent && canSelectFrame) {
      final score = _portraitScore(nextSignal);
      final previousBest = bestFrame;
      if (score >= bestFrameScore) {
        bestFrameScore = score;
        bestFrame = frame;
        if (previousBest != null && previousBest.path != frame.path) {
          unawaited(previousBest.delete().catchError((_) => previousBest));
        }
      } else if (previousBest?.path != frame.path) {
        unawaited(frame.delete().catchError((_) => File(frame.path)));
      }
    }
    if (portraitMode &&
        portraitLockedAt != null &&
        !portraitCapturePending &&
        !completing) {
      _schedulePortraitCapture();
    }
    if (!shouldUpdate || !mounted) return;
    lastUiUpdate = now;
    setState(() {
      signal = nextSignal;
      message = nextMessage;
    });
  }

  void _schedulePortraitCapture() {
    portraitCapturePending = true;
    analysisTimer?.cancel();
    portraitCaptureTimer?.cancel();
    portraitCaptureTimer = Timer(
      Platform.isWindows
          ? const Duration(milliseconds: 850)
          : const Duration(seconds: 2),
      () {
        unawaited(_captureLockedPortrait());
      },
    );
  }

  Future<void> _captureLockedPortrait() async {
    final active = controller;
    if (!mounted || completing) return;
    if (active == null ||
        !active.value.isInitialized ||
        !previewReady ||
        active.value.isTakingPicture) {
      _restartPortraitSearch();
      return;
    }
    analyzing = true;
    try {
      final image = await active.takePicture();
      final finalFrame = File(image.path);
      final previousBest = bestFrame;
      bestFrame = finalFrame;
      if (previousBest != null && previousBest.path != finalFrame.path) {
        unawaited(previousBest.delete().catchError((_) => previousBest));
      }
      if (!mounted) {
        unawaited(finalFrame.delete().catchError((_) => finalFrame));
        return;
      }
      await _completeScan(finalFrame);
    } catch (error) {
      debugPrint('ExamVerify official portrait capture failed: $error');
      if (mounted) {
        _restartPortraitSearch();
      }
    } finally {
      analyzing = false;
    }
  }

  void _restartPortraitSearch() {
    portraitCapturePending = false;
    portraitLockedAt = null;
    if (!mounted || completing) return;
    setState(() {
      cameraState = _BiometricCameraState.portraitCapture;
      message = 'Hold still while the camera reacquires your portrait.';
    });
    _startAnalysisTimer(interval: const Duration(milliseconds: 1000));
  }

  double _portraitScore(FaceSignal nextSignal) {
    final frontal =
        1 -
        ((nextSignal.yaw.abs() / 28) +
                (nextSignal.pitch.abs() / 28) +
                (nextSignal.roll.abs() / 28))
            .clamp(0, 1);
    final eyes = ((nextSignal.leftEyeOpen + nextSignal.rightEyeOpen) / 2).clamp(
      0,
      1,
    );
    return (nextSignal.quality * 0.48) + (frontal * 0.36) + (eyes * 0.16);
  }

  double _averageEyeOpen(FaceSignal faceSignal) {
    return ((faceSignal.leftEyeOpen + faceSignal.rightEyeOpen) / 2).clamp(
      0.0,
      1.0,
    );
  }

  void _enterPortraitMode(File livenessFrame) {
    final previousBest = bestFrame;
    if (previousBest != null && previousBest.path != livenessFrame.path) {
      unawaited(previousBest.delete().catchError((_) => previousBest));
    }
    unawaited(livenessFrame.delete().catchError((_) => livenessFrame));
    setState(() {
      challenges = _buildChallenges(BiometricScanMode.portrait);
      challengeIndex = 0;
      blinkCount = 0;
      blinkFallbackFrames = 0;
      challengeStableFrames = 0;
      portraitLockedAt = null;
      portraitCapturePending = false;
      completedChallengeLabels.clear();
      wasClosed = false;
      signal = null;
      centeredBaseline = null;
      bestFrame = null;
      bestFrameScore = 0;
      challengeStartedAt = DateTime.now();
      cameraState = _BiometricCameraState.portraitCapture;
      message = 'Perfect! Center your face and look at the camera.';
    });
    _startAnalysisTimer(interval: const Duration(milliseconds: 1000));
  }

  Future<void> _completeScan(File fallbackFrame) async {
    if (completing) return;
    completing = true;
    analysisTimer?.cancel();
    portraitCaptureTimer?.cancel();
    setState(() {
      cameraState = _BiometricCameraState.complete;
      message =
          widget.mode == BiometricScanMode.enrollment ||
              widget.mode == BiometricScanMode.portrait
          ? 'Official portrait captured.'
          : 'Biometric profile locked.';
    });
    await Future<void>.delayed(const Duration(milliseconds: 420));
    returnedFrame = true;
    if (mounted) Navigator.of(context).pop(bestFrame ?? fallbackFrame);
  }

  String get _title => switch (widget.mode) {
    BiometricScanMode.enrollment => 'Biometric Enrollment',
    BiometricScanMode.portrait => 'Official Portrait Capture',
    BiometricScanMode.verification => 'Live Verification',
    BiometricScanMode.autoIdentify => 'Auto Identify Scanner',
  };

  @override
  Widget build(BuildContext context) {
    final active = controller;
    final current = challenges[challengeIndex];
    final progress = (challengeIndex + 1) / challenges.length;
    if (Platform.isWindows && MediaQuery.sizeOf(context).width >= 760) {
      return _DesktopBiometricScannerScaffold(
        title: _title,
        controller: active,
        cameraReady: _cameraReady,
        hasError: cameraState == _BiometricCameraState.error,
        onRetry: _openCamera,
        animation: animation,
        challenge: current,
        message: message,
        progress: progress,
        signal: signal,
        blinkCount: blinkCount,
        completedCount: challengeIndex,
        completedLabels: completedChallengeLabels,
        showBlinkStatus: current.type != _BiometricChallengeType.centerFinal,
      );
    }
    return Scaffold(
      backgroundColor: const Color(0xFF020712),
      body: SafeArea(
        child: Stack(
          children: [
            Positioned.fill(
              child: _cameraReady
                  ? FittedBox(
                      fit: BoxFit.cover,
                      child: SizedBox(
                        width: active!.value.previewSize?.height ?? 720,
                        height: active.value.previewSize?.width ?? 1280,
                        child: camera.CameraPreview(active),
                      ),
                    )
                  : const Center(
                      child: CircularProgressIndicator(color: AppColors.cyan),
                    ),
            ),
            Positioned.fill(
              child: _cameraReady
                  ? RepaintBoundary(
                      child: AnimatedBuilder(
                        animation: animation,
                        builder: (context, _) => CustomPaint(
                          painter: _BiometricScannerPainter(
                            progress: animation.value,
                            statusProgress: progress,
                            signal: signal,
                            challenge: current.type,
                          ),
                        ),
                      ),
                    )
                  : const SizedBox.shrink(),
            ),
            if (cameraState == _BiometricCameraState.error)
              Center(
                child: _CameraErrorPanel(
                  message: message,
                  onRetry: _openCamera,
                ),
              ),
            Positioned.fill(
              child: DecoratedBox(
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      Colors.black.withValues(alpha: 0.50),
                      Colors.transparent,
                      Colors.black.withValues(alpha: 0.72),
                    ],
                  ),
                ),
              ),
            ),
            Positioned(
              left: 18,
              right: 18,
              top: 16,
              child: Row(
                children: [
                  IconButton.filledTonal(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _title,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 18,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const Text(
                          'REAL-TIME BIOMETRIC CHALLENGE',
                          style: TextStyle(
                            color: AppColors.cyan,
                            fontSize: 11,
                            fontWeight: FontWeight.w800,
                            letterSpacing: 1,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (_canSwitchMobileCamera)
                    IconButton.filledTonal(
                      tooltip: selectedLens == camera.CameraLensDirection.front
                          ? 'Use back camera'
                          : 'Use front camera',
                      onPressed: _switchMobileCamera,
                      icon: const Icon(Icons.cameraswitch_outlined),
                    ),
                ],
              ),
            ),
            Positioned(
              left: 18,
              right: 18,
              bottom: 20,
              child: _ScannerStatusPanel(
                challenge: current,
                message: message,
                progress: progress,
                signal: signal,
                blinkCount: blinkCount,
                completedCount: challengeIndex,
                completedLabels: completedChallengeLabels,
                showBlinkStatus:
                    current.type != _BiometricChallengeType.centerFinal,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

class _DesktopBiometricScannerScaffold extends StatelessWidget {
  const _DesktopBiometricScannerScaffold({
    required this.title,
    required this.controller,
    required this.cameraReady,
    required this.hasError,
    required this.onRetry,
    required this.animation,
    required this.challenge,
    required this.message,
    required this.progress,
    required this.signal,
    required this.blinkCount,
    required this.completedCount,
    required this.completedLabels,
    required this.showBlinkStatus,
  });

  final String title;
  final camera.CameraController? controller;
  final bool cameraReady;
  final bool hasError;
  final VoidCallback onRetry;
  final Animation<double> animation;
  final _BiometricChallenge challenge;
  final String message;
  final double progress;
  final FaceSignal? signal;
  final int blinkCount;
  final int completedCount;
  final List<String> completedLabels;
  final bool showBlinkStatus;

  @override
  Widget build(BuildContext context) {
    final active = controller;
    final previewSize = active?.value.previewSize;
    final previewAspect = previewSize == null || previewSize.height == 0
        ? 16 / 9
        : (previewSize.width / previewSize.height).clamp(1.32, 1.90);
    return Scaffold(
      backgroundColor: const Color(0xFF020712),
      body: SafeArea(
        child: Center(
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1060, maxHeight: 760),
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Container(
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(
                  color: AppColors.panel,
                  borderRadius: BorderRadius.circular(24),
                  border: Border.all(
                    color: AppColors.cyan.withValues(alpha: 0.24),
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: AppColors.cyan.withValues(alpha: 0.10),
                      blurRadius: 36,
                      offset: const Offset(0, 18),
                    ),
                  ],
                ),
                child: Column(
                  children: [
                    Row(
                      children: [
                        IconButton.filledTonal(
                          onPressed: () => Navigator.of(context).pop(),
                          icon: const Icon(Icons.close),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                title,
                                style: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 20,
                                  fontWeight: FontWeight.w900,
                                ),
                              ),
                              const Text(
                                'KIOSK BIOMETRIC SCAN PANEL',
                                style: TextStyle(
                                  color: AppColors.cyan,
                                  fontSize: 11,
                                  fontWeight: FontWeight.w800,
                                  letterSpacing: 1,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 14),
                    Expanded(
                      child: Row(
                        children: [
                          Expanded(
                            flex: 7,
                            child: Align(
                              alignment: Alignment.center,
                              child: ConstrainedBox(
                                constraints: const BoxConstraints(
                                  maxWidth: 700,
                                  maxHeight: 420,
                                ),
                                child: ClipRRect(
                                  borderRadius: BorderRadius.circular(18),
                                  child: AspectRatio(
                                    aspectRatio: previewAspect,
                                    child: Stack(
                                      fit: StackFit.expand,
                                      children: [
                                        if (cameraReady && active != null)
                                          FittedBox(
                                            fit: BoxFit.cover,
                                            child: SizedBox(
                                              width:
                                                  active
                                                      .value
                                                      .previewSize
                                                      ?.width ??
                                                  720,
                                              height:
                                                  active
                                                      .value
                                                      .previewSize
                                                      ?.height ??
                                                  1280,
                                              child: camera.CameraPreview(
                                                active,
                                              ),
                                            ),
                                          )
                                        else
                                          Container(
                                            color: const Color(0xFF071327),
                                            alignment: Alignment.center,
                                            child: hasError
                                                ? _CameraErrorPanel(
                                                    message: message,
                                                    onRetry: onRetry,
                                                  )
                                                : const CircularProgressIndicator(
                                                    color: AppColors.cyan,
                                                  ),
                                          ),
                                        if (cameraReady)
                                          RepaintBoundary(
                                            child: AnimatedBuilder(
                                              animation: animation,
                                              builder: (context, _) =>
                                                  CustomPaint(
                                                    painter:
                                                        _BiometricScannerPainter(
                                                          progress:
                                                              animation.value,
                                                          statusProgress:
                                                              progress,
                                                          signal: signal,
                                                          challenge:
                                                              challenge.type,
                                                          desktop: true,
                                                        ),
                                                  ),
                                            ),
                                          ),
                                      ],
                                    ),
                                  ),
                                ),
                              ),
                            ),
                          ),
                          const SizedBox(width: 18),
                          Expanded(
                            flex: 4,
                            child: Align(
                              alignment: Alignment.bottomCenter,
                              child: _ScannerStatusPanel(
                                challenge: challenge,
                                message: message,
                                progress: progress,
                                signal: signal,
                                blinkCount: blinkCount,
                                completedCount: completedCount,
                                completedLabels: completedLabels,
                                showBlinkStatus: showBlinkStatus,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ScannerStatusPanel extends StatelessWidget {
  const _ScannerStatusPanel({
    required this.challenge,
    required this.message,
    required this.progress,
    required this.signal,
    required this.blinkCount,
    required this.completedCount,
    required this.completedLabels,
    required this.showBlinkStatus,
  });

  final _BiometricChallenge challenge;
  final String message;
  final double progress;
  final FaceSignal? signal;
  final int blinkCount;
  final int completedCount;
  final List<String> completedLabels;
  final bool showBlinkStatus;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(24),
      child: BackdropFilter(
        filter: ImageFilter.blur(sigmaX: 20, sigmaY: 20),
        child: Container(
          padding: const EdgeInsets.all(18),
          decoration: BoxDecoration(
            color: const Color(0xCC071327),
            borderRadius: BorderRadius.circular(24),
            border: Border.all(color: AppColors.cyan.withValues(alpha: 0.28)),
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  Container(
                    width: 46,
                    height: 46,
                    decoration: BoxDecoration(
                      shape: BoxShape.circle,
                      color: AppColors.cyan.withValues(alpha: 0.13),
                      border: Border.all(color: AppColors.cyan),
                    ),
                    child: const Icon(
                      Icons.center_focus_strong_outlined,
                      color: AppColors.cyan,
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          challenge.label,
                          style: const TextStyle(
                            color: Colors.white,
                            fontSize: 20,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const SizedBox(height: 4),
                        Text(
                          message,
                          style: const TextStyle(color: AppColors.soft),
                        ),
                      ],
                    ),
                  ),
                  Text(
                    '${(progress * 100).round()}%',
                    style: const TextStyle(
                      color: AppColors.cyan,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 14),
              ClipRRect(
                borderRadius: BorderRadius.circular(999),
                child: LinearProgressIndicator(
                  value: progress,
                  minHeight: 7,
                  backgroundColor: Colors.white.withValues(alpha: 0.08),
                  color: AppColors.cyan,
                ),
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  for (final label in completedLabels.take(3))
                    _SignalChip(
                      label: '$label verified',
                      color: AppColors.green,
                    ),
                  _SignalChip(
                    label: signal?.facePresent == true
                        ? 'Face locked'
                        : 'Searching',
                    color: signal?.facePresent == true
                        ? AppColors.green
                        : AppColors.amber,
                  ),
                  _SignalChip(
                    label:
                        'Quality ${(((signal?.quality ?? 0) * 100).round())}%',
                    color: AppColors.cyan,
                  ),
                  if (showBlinkStatus)
                    _SignalChip(
                      label: 'Blinks $blinkCount/1',
                      color: AppColors.green,
                    ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CameraErrorPanel extends StatelessWidget {
  const _CameraErrorPanel({required this.message, required this.onRetry});

  final String message;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 320,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: AppColors.panel.withValues(alpha: 0.92),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: AppColors.red.withValues(alpha: 0.38)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(Icons.videocam_off_outlined, color: AppColors.red),
          const SizedBox(height: 10),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: Colors.white,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 14),
          FilledButton.icon(
            onPressed: onRetry,
            icon: const Icon(Icons.refresh),
            label: const Text('Retry Camera'),
          ),
        ],
      ),
    );
  }
}

class _SignalChip extends StatelessWidget {
  const _SignalChip({required this.label, required this.color});

  final String label;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.12),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: color.withValues(alpha: 0.45)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: color,
          fontSize: 12,
          fontWeight: FontWeight.w800,
        ),
      ),
    );
  }
}

class _BiometricScannerPainter extends CustomPainter {
  const _BiometricScannerPainter({
    required this.progress,
    required this.statusProgress,
    required this.signal,
    required this.challenge,
    this.desktop = false,
  });

  final double progress;
  final double statusProgress;
  final FaceSignal? signal;
  final _BiometricChallengeType challenge;
  final bool desktop;

  @override
  void paint(Canvas canvas, Size size) {
    final center = Offset(size.width / 2, size.height / 2);
    final scanRect = desktop
        ? Rect.fromCenter(
            center: center,
            width: math.min(size.width * 0.38, 252),
            height: math.min(size.height * 0.82, 330),
          )
        : Rect.fromCenter(
            center: center,
            width: math.min(size.width * 0.78, 440),
            height: math.min(size.height * 0.54, 560),
          );
    final glow = Paint()
      ..color = AppColors.cyan.withValues(alpha: 0.28)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.6
      ..maskFilter = const MaskFilter.blur(BlurStyle.normal, 8);
    final border = Paint()
      ..color = signal?.facePresent == true ? AppColors.green : AppColors.cyan
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0
      ..strokeCap = StrokeCap.round;
    canvas.drawRRect(
      RRect.fromRectAndRadius(scanRect, const Radius.circular(32)),
      glow,
    );
    canvas.drawRRect(
      RRect.fromRectAndRadius(scanRect, const Radius.circular(32)),
      border,
    );
    final lineY = scanRect.top + (scanRect.height * progress);
    final linePaint = Paint()
      ..shader =
          LinearGradient(
            colors: [
              Colors.transparent,
              AppColors.cyan.withValues(alpha: 0.85),
              Colors.transparent,
            ],
          ).createShader(
            Rect.fromLTWH(scanRect.left, lineY - 20, scanRect.width, 40),
          )
      ..strokeWidth = 3;
    canvas.drawLine(
      Offset(scanRect.left + 24, lineY),
      Offset(scanRect.right - 24, lineY),
      linePaint,
    );
    final meshPaint = Paint()
      ..color = AppColors.cyan.withValues(alpha: 0.22)
      ..strokeWidth = 1;
    for (var i = 0; i < 9; i++) {
      final x = scanRect.left + scanRect.width * (i / 8);
      canvas.drawLine(
        Offset(x, scanRect.top + 24),
        Offset(x, scanRect.bottom - 24),
        meshPaint,
      );
    }
    for (var i = 0; i < 11; i++) {
      final y = scanRect.top + scanRect.height * (i / 10);
      canvas.drawLine(
        Offset(scanRect.left + 24, y),
        Offset(scanRect.right - 24, y),
        meshPaint,
      );
    }
    final arcPaint = Paint()
      ..color = AppColors.cyan
      ..style = PaintingStyle.stroke
      ..strokeWidth = 4
      ..strokeCap = StrokeCap.round;
    canvas.drawArc(
      scanRect.inflate(14),
      -math.pi / 2,
      math.pi * 2 * statusProgress,
      false,
      arcPaint,
    );
    _drawGuidance(canvas, scanRect);
  }

  void _drawGuidance(Canvas canvas, Rect scanRect) {
    final paint = Paint()
      ..color = AppColors.cyan.withValues(alpha: 0.72)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 3
      ..strokeCap = StrokeCap.round;
    final center = scanRect.center;
    switch (challenge) {
      case _BiometricChallengeType.lookLeft:
        canvas.drawLine(
          center.translate(34, 0),
          center.translate(-42, 0),
          paint,
        );
        canvas.drawLine(
          center.translate(-42, 0),
          center.translate(-24, -16),
          paint,
        );
        canvas.drawLine(
          center.translate(-42, 0),
          center.translate(-24, 16),
          paint,
        );
      case _BiometricChallengeType.lookRight:
        canvas.drawLine(
          center.translate(-34, 0),
          center.translate(42, 0),
          paint,
        );
        canvas.drawLine(
          center.translate(42, 0),
          center.translate(24, -16),
          paint,
        );
        canvas.drawLine(
          center.translate(42, 0),
          center.translate(24, 16),
          paint,
        );
      case _BiometricChallengeType.lookUp:
        canvas.drawLine(
          center.translate(0, 36),
          center.translate(0, -42),
          paint,
        );
        canvas.drawLine(
          center.translate(0, -42),
          center.translate(-16, -24),
          paint,
        );
        canvas.drawLine(
          center.translate(0, -42),
          center.translate(16, -24),
          paint,
        );
      case _BiometricChallengeType.tilt:
        canvas.drawLine(
          center.translate(-30, 24),
          center.translate(32, -24),
          paint,
        );
        canvas.drawLine(
          center.translate(32, -24),
          center.translate(11, -28),
          paint,
        );
        canvas.drawLine(
          center.translate(32, -24),
          center.translate(26, -2),
          paint,
        );
      case _BiometricChallengeType.blink:
        canvas.drawOval(
          Rect.fromCenter(
            center: center.translate(-42, -18),
            width: 44,
            height: 16,
          ),
          paint,
        );
        canvas.drawOval(
          Rect.fromCenter(
            center: center.translate(42, -18),
            width: 44,
            height: 16,
          ),
          paint,
        );
      case _BiometricChallengeType.centerInitial:
      case _BiometricChallengeType.centerFinal:
        canvas.drawOval(
          Rect.fromCenter(
            center: center,
            width: scanRect.width * 0.44,
            height: scanRect.height * 0.58,
          ),
          paint..color = AppColors.cyan.withValues(alpha: 0.30),
        );
    }
  }

  @override
  bool shouldRepaint(covariant _BiometricScannerPainter oldDelegate) {
    return oldDelegate.progress != progress ||
        oldDelegate.statusProgress != statusProgress ||
        oldDelegate.signal != signal ||
        oldDelegate.challenge != challenge ||
        oldDelegate.desktop != desktop;
  }
}

class CameraCaptureDialog extends StatefulWidget {
  const CameraCaptureDialog({super.key});

  @override
  State<CameraCaptureDialog> createState() => _CameraCaptureDialogState();
}

class _CameraCaptureDialogState extends State<CameraCaptureDialog> {
  camera.CameraController? controller;
  String? message;
  bool capturing = false;

  @override
  void initState() {
    super.initState();
    _openCamera();
  }

  @override
  void dispose() {
    controller?.dispose();
    super.dispose();
  }

  Future<void> _openCamera() async {
    try {
      final cameras = await camera.availableCameras();
      if (cameras.isEmpty) {
        setState(() => message = 'No camera was found on this device.');
        return;
      }
      final selectedCamera = cameras.firstWhere(
        (item) => item.lensDirection == camera.CameraLensDirection.front,
        orElse: () => cameras.first,
      );
      final nextController = camera.CameraController(
        selectedCamera,
        camera.ResolutionPreset.medium,
        enableAudio: false,
      );
      await nextController.initialize();
      if (!mounted) {
        await nextController.dispose();
        return;
      }
      setState(() => controller = nextController);
    } catch (error) {
      if (!mounted) return;
      setState(() => message = 'Could not open camera: $error');
    }
  }

  Future<void> _capture() async {
    final activeController = controller;
    if (activeController == null || !activeController.value.isInitialized) {
      return;
    }
    setState(() => capturing = true);
    try {
      final image = await activeController.takePicture();
      if (!mounted) return;
      Navigator.of(context).pop(File(image.path));
    } catch (error) {
      if (!mounted) return;
      setState(() {
        capturing = false;
        message = 'Could not capture photo: $error';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    final activeController = controller;
    return Dialog(
      backgroundColor: AppColors.panel,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.photo_camera_outlined,
                    color: AppColors.cyan,
                  ),
                  const SizedBox(width: 10),
                  const Expanded(
                    child: Text(
                      'Live Camera Capture',
                      style: TextStyle(
                        color: Colors.white,
                        fontWeight: FontWeight.w900,
                        fontSize: 18,
                      ),
                    ),
                  ),
                  IconButton(
                    onPressed: () => Navigator.of(context).pop(),
                    icon: const Icon(Icons.close),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: Container(
                  height: 360,
                  width: double.infinity,
                  color: const Color(0xFF071327),
                  child:
                      activeController != null &&
                          activeController.value.isInitialized
                      ? camera.CameraPreview(activeController)
                      : Center(
                          child: message == null
                              ? const CircularProgressIndicator(
                                  color: AppColors.cyan,
                                )
                              : Padding(
                                  padding: const EdgeInsets.all(18),
                                  child: Text(
                                    message!,
                                    textAlign: TextAlign.center,
                                    style: const TextStyle(
                                      color: AppColors.muted,
                                    ),
                                  ),
                                ),
                        ),
                ),
              ),
              const SizedBox(height: 10),
              const Text(
                'Face the camera directly and keep the face centered before capturing.',
                style: TextStyle(color: AppColors.muted),
              ),
              const SizedBox(height: 16),
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => Navigator.of(context).pop(),
                      child: const Text('Cancel'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed:
                          capturing ||
                              activeController == null ||
                              !activeController.value.isInitialized
                          ? null
                          : _capture,
                      icon: capturing
                          ? const SizedBox(
                              height: 18,
                              width: 18,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Icon(Icons.camera_alt_outlined),
                      label: Text(capturing ? 'Capturing...' : 'Capture'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class AppTextField extends StatelessWidget {
  const AppTextField({
    required this.controller,
    required this.label,
    this.required = true,
    super.key,
  });

  final TextEditingController controller;
  final String label;
  final bool required;

  @override
  Widget build(BuildContext context) {
    return TextFormField(
      controller: controller,
      decoration: InputDecoration(labelText: label),
      validator: (value) {
        if (!required) return null;
        if (value == null || value.trim().isEmpty) return '$label is required';
        return null;
      },
    );
  }
}

class AppScrollView extends StatelessWidget {
  const AppScrollView({required this.child, super.key});

  final Widget child;

  @override
  Widget build(BuildContext context) {
    final width = MediaQuery.sizeOf(context).width;
    final padding = width < 520 ? 16.0 : 24.0;
    return SafeArea(
      child: SingleChildScrollView(
        keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
        padding: EdgeInsets.all(padding),
        child: Align(
          alignment: Alignment.topCenter,
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 1380),
            child: child,
          ),
        ),
      ),
    );
  }
}

class PageHero extends StatelessWidget {
  const PageHero({required this.title, required this.subtitle, super.key});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(14),
        border: Border.all(color: AppColors.cyanSoft),
        boxShadow: const [
          BoxShadow(
            color: Color(0x33000000),
            blurRadius: 36,
            offset: Offset(0, 18),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'BIOMETRIC VERIFICATION SYSTEM',
            style: TextStyle(
              color: AppColors.cyan,
              fontSize: 12,
              fontWeight: FontWeight.w900,
              letterSpacing: 1.1,
            ),
          ),
          const SizedBox(height: 7),
          Text(
            title,
            style: Theme.of(context).textTheme.headlineSmall?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            subtitle,
            style: const TextStyle(color: AppColors.soft, fontSize: 15),
          ),
        ],
      ),
    );
  }
}

class SectionTitle extends StatelessWidget {
  const SectionTitle({required this.title, required this.subtitle, super.key});

  final String title;
  final String subtitle;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(0, 22, 0, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: Theme.of(context).textTheme.titleMedium?.copyWith(
              color: Colors.white,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: const TextStyle(color: AppColors.muted, fontSize: 13),
          ),
          const SizedBox(height: 12),
          const Divider(color: AppColors.border, height: 1),
        ],
      ),
    );
  }
}

class MetricCard extends StatelessWidget {
  const MetricCard({
    required this.label,
    required this.value,
    required this.accent,
    super.key,
  });

  final String label;
  final String value;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return PanelCard(
      accent: accent,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            label.toUpperCase(),
            style: const TextStyle(
              color: AppColors.muted,
              fontSize: 11,
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            value,
            style: TextStyle(
              color: accent,
              fontSize: 30,
              fontWeight: FontWeight.w900,
            ),
          ),
        ],
      ),
    );
  }
}

class FeatureCard extends StatelessWidget {
  const FeatureCard({
    required this.title,
    required this.value,
    required this.icon,
    super.key,
  });

  final String title;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return PanelCard(
      child: Row(
        children: [
          Container(
            width: 42,
            height: 42,
            decoration: BoxDecoration(
              color: AppColors.cyan.withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(10),
              border: Border.all(color: AppColors.cyanSoft),
            ),
            child: Icon(icon, color: AppColors.cyan),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 5),
                Text(
                  value,
                  style: const TextStyle(
                    color: AppColors.soft,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class VerificationLogCard extends StatelessWidget {
  const VerificationLogCard({required this.record, super.key});

  final VerificationRecord record;

  @override
  Widget build(BuildContext context) {
    final accent = switch (record.status) {
      VerificationStatus.verified => AppColors.green,
      VerificationStatus.spoofDetected => AppColors.amber,
      VerificationStatus.notVerified => AppColors.red,
    };
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: PanelCard(
        borderColor: accent.withValues(alpha: 0.35),
        child: LayoutBuilder(
          builder: (context, constraints) {
            final compact = constraints.maxWidth < 640;
            final statusPill = StatusPill(
              label: record.status.label,
              tone: accent,
            );
            final scoreText = Text(
              'Score ${record.score.toStringAsFixed(2)}',
              textAlign: compact ? TextAlign.left : TextAlign.right,
              style: const TextStyle(
                color: AppColors.soft,
                fontWeight: FontWeight.w800,
              ),
            );
            final identity = Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  record.fullName,
                  style: const TextStyle(
                    color: Colors.white,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  '#${AuthService.maskIdentifier(record.studentNumber)} / hash ${record.studentNumberHashShort}',
                  style: const TextStyle(color: AppColors.muted, fontSize: 12),
                ),
                const SizedBox(height: 3),
                Text(
                  record.programLabel,
                  style: const TextStyle(color: AppColors.soft, fontSize: 12),
                ),
              ],
            );
            final timeText = Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  record.timeLabel,
                  style: const TextStyle(color: AppColors.muted, fontSize: 12),
                ),
              ],
            );
            final portrait = _VerificationStoredPortrait(
              path: record.storedImagePath,
            );

            if (compact) {
              return Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  timeText,
                  const SizedBox(height: 10),
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(child: identity),
                      const SizedBox(width: 12),
                      portrait,
                    ],
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 12,
                    runSpacing: 10,
                    children: [statusPill, scoreText],
                  ),
                ],
              );
            }

            return Row(
              children: [
                SizedBox(width: 172, child: timeText),
                Expanded(child: identity),
                const SizedBox(width: 16),
                portrait,
                const SizedBox(width: 18),
                statusPill,
                const SizedBox(width: 18),
                SizedBox(width: 110, child: scoreText),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _VerificationStoredPortrait extends StatelessWidget {
  const _VerificationStoredPortrait({required this.path});

  final String? path;

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: BorderRadius.circular(14),
      child: Container(
        width: 82,
        height: 96,
        decoration: BoxDecoration(
          color: const Color(0xFF071327),
          border: Border.all(color: AppColors.border),
        ),
        child: path == null || path!.isEmpty
            ? const Icon(Icons.badge_outlined, color: AppColors.muted)
            : _StoredPortrait(path: path!),
      ),
    );
  }
}

class EmptyState extends StatelessWidget {
  const EmptyState({required this.message, super.key});

  final String message;

  @override
  Widget build(BuildContext context) {
    return PanelCard(
      child: Row(
        children: [
          const Icon(Icons.info_outline, color: AppColors.cyan),
          const SizedBox(width: 12),
          Expanded(
            child: Text(message, style: const TextStyle(color: AppColors.soft)),
          ),
        ],
      ),
    );
  }
}

class PanelCard extends StatelessWidget {
  const PanelCard({
    required this.child,
    this.accent,
    this.borderColor,
    super.key,
  });

  final Widget child;
  final Color? accent;
  final Color? borderColor;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: AppColors.panel,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: borderColor ?? AppColors.border),
        boxShadow: const [
          BoxShadow(
            color: Color(0x26000000),
            blurRadius: 30,
            offset: Offset(0, 16),
          ),
        ],
      ),
      child: Stack(
        children: [
          if (accent != null)
            Positioned(
              top: -16,
              left: -16,
              right: -16,
              child: Container(height: 3, color: accent),
            ),
          child,
        ],
      ),
    );
  }
}

class StatusPill extends StatelessWidget {
  const StatusPill({required this.label, required this.tone, super.key});

  final String label;
  final Color tone;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
      decoration: BoxDecoration(
        color: tone.withValues(alpha: 0.13),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: tone.withValues(alpha: 0.42)),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: tone,
          fontSize: 11,
          fontWeight: FontWeight.w900,
        ),
      ),
    );
  }
}

class NavItem {
  const NavItem(
    this.icon,
    this.label, {
    this.roles = const {'Super Admin', 'Admin', 'Invigilator', 'Viewer'},
  });

  final IconData icon;
  final String label;
  final Set<String> roles;
}

class StudentRecord {
  const StudentRecord({
    this.id,
    required this.studentNumber,
    this.studentNumberHash,
    required this.fullName,
    required this.program,
    this.level = '',
    this.status = 'active',
    required this.eligible,
    required this.note,
    required this.photoPath,
    required this.signature,
    this.backendEmbedding,
    this.backendName,
  });

  final int? id;
  final String studentNumber;
  final String? studentNumberHash;
  final String fullName;
  final String program;
  final String level;
  final String status;
  final bool eligible;
  final String note;
  final String photoPath;
  final List<double> signature;
  final String? backendEmbedding;
  final String? backendName;

  StudentRecord copyWith({
    bool? eligible,
    String? backendEmbedding,
    String? backendName,
  }) {
    return StudentRecord(
      id: id,
      studentNumber: studentNumber,
      studentNumberHash:
          studentNumberHash ?? AuthService.hashIdentifier(studentNumber),
      fullName: fullName,
      program: program,
      level: level,
      status: status,
      eligible: eligible ?? this.eligible,
      note: note,
      photoPath: photoPath,
      signature: signature,
      backendEmbedding: backendEmbedding ?? this.backendEmbedding,
      backendName: backendName ?? this.backendName,
    );
  }

  Map<String, Object?> toMap() {
    return {
      'id': id,
      'student_number': studentNumber,
      'student_number_hash':
          studentNumberHash ?? AuthService.hashIdentifier(studentNumber),
      'full_name': fullName,
      'program': program,
      'level': level,
      'student_status': status,
      'eligible': eligible ? 1 : 0,
      'note': note,
      'photo_path': photoPath,
      'signature_json': jsonEncode(signature),
      'backend_embedding': backendEmbedding,
      'backend_name': backendName,
      'created_at': DateTime.now().toIso8601String(),
    };
  }

  static StudentRecord fromMap(Map<String, Object?> map) {
    return StudentRecord(
      id: map['id'] as int?,
      studentNumber: map['student_number'] as String,
      studentNumberHash:
          map['student_number_hash'] as String? ??
          AuthService.hashIdentifier(map['student_number'] as String),
      fullName: map['full_name'] as String,
      program: (map['program'] as String?) ?? '',
      level: (map['level'] as String?) ?? '',
      status: (map['student_status'] as String?) ?? 'active',
      eligible: (map['eligible'] as int? ?? 1) == 1,
      note: (map['note'] as String?) ?? '',
      photoPath: map['photo_path'] as String,
      signature: [
        for (final value in jsonDecode(map['signature_json'] as String) as List)
          (value as num).toDouble(),
      ],
      backendEmbedding: map['backend_embedding'] as String?,
      backendName: map['backend_name'] as String?,
    );
  }

  static StudentRecord fromApi(Map<String, dynamic> map) {
    final profile =
        map['biometric_profile'] as Map<String, dynamic>? ??
        const <String, dynamic>{};
    final number =
        (map['student_number'] as String?) ??
        (map['student_number_mask'] as String?) ??
        '';
    return StudentRecord(
      id: map['id'] as int?,
      studentNumber: number,
      studentNumberHash:
          map['student_number_hash'] as String? ??
          AuthService.hashIdentifier(number),
      fullName: (map['full_name'] as String?) ?? 'Unknown student',
      program: (map['program'] as String?) ?? '',
      level: (map['level'] as String?) ?? '',
      status: (map['status'] as String?) ?? 'active',
      eligible: (map['exam_eligible'] as int? ?? 1) == 1,
      note: (map['eligibility_note'] as String?) ?? '',
      photoPath:
          (map['photo_path'] as String?) ?? (map['photo_url'] as String? ?? ''),
      signature: [
        for (final value in (profile['signature'] as List? ?? const []))
          (value as num).toDouble(),
      ],
      backendEmbedding: map['face_embedding'] as String?,
      backendName:
          map['embedding_backend'] as String? ??
          profile['embedding_backend'] as String?,
    );
  }
}

class ExamSessionRecord {
  const ExamSessionRecord({
    required this.id,
    required this.courseCode,
    required this.courseName,
    required this.program,
    required this.level,
    required this.examDate,
    required this.startTime,
    required this.endTime,
    required this.venue,
    required this.status,
  });

  final int id;
  final String courseCode;
  final String courseName;
  final String program;
  final String level;
  final String examDate;
  final String startTime;
  final String endTime;
  final String venue;
  final String status;

  bool get isActive => status == 'active';
  String get label => '$courseCode - $courseName ($venue)';

  Map<String, Object?> toMap() => {
    'id': id,
    'course_code': courseCode,
    'course_name': courseName,
    'program': program,
    'level': level,
    'exam_date': examDate,
    'start_time': startTime,
    'end_time': endTime,
    'venue': venue,
    'status': status,
  };

  static ExamSessionRecord fromMap(Map<String, Object?> map) =>
      ExamSessionRecord(
        id: (map['id'] as num).toInt(),
        courseCode: (map['course_code'] as String?) ?? '',
        courseName: (map['course_name'] as String?) ?? '',
        program: (map['program'] as String?) ?? '',
        level: (map['level'] as String?) ?? '',
        examDate: (map['exam_date'] as String?) ?? '',
        startTime: (map['start_time'] as String?) ?? '',
        endTime: (map['end_time'] as String?) ?? '',
        venue: (map['venue'] as String?) ?? '',
        status: (map['status'] as String?) ?? 'scheduled',
      );
}

class ExamEligibilityRecord {
  const ExamEligibilityRecord({
    required this.id,
    required this.examSessionId,
    required this.studentId,
    required this.eligibilityType,
    required this.eligibilityStatus,
    required this.attendanceStatus,
    this.verifiedAt,
  });

  final int id;
  final int examSessionId;
  final int studentId;
  final String eligibilityType;
  final String eligibilityStatus;
  final String attendanceStatus;
  final String? verifiedAt;

  bool get mayEnter =>
      eligibilityStatus == 'eligible' && attendanceStatus != 'verified';

  Map<String, Object?> toMap() => {
    'id': id,
    'exam_session_id': examSessionId,
    'student_id': studentId,
    'eligibility_type': eligibilityType,
    'eligibility_status': eligibilityStatus,
    'attendance_status': attendanceStatus,
    'verified_at': verifiedAt,
  };

  static ExamEligibilityRecord fromMap(Map<String, Object?> map) =>
      ExamEligibilityRecord(
        id: (map['id'] as num).toInt(),
        examSessionId: (map['exam_session_id'] as num).toInt(),
        studentId: (map['student_id'] as num).toInt(),
        eligibilityType: (map['eligibility_type'] as String?) ?? 'regular',
        eligibilityStatus: (map['eligibility_status'] as String?) ?? 'eligible',
        attendanceStatus:
            (map['attendance_status'] as String?) ?? 'not_verified',
        verifiedAt: map['verified_at'] as String?,
      );
}

class ExamEntryDecision {
  const ExamEntryDecision({
    required this.decision,
    required this.reason,
    this.eligibilityType,
  });

  final String decision;
  final String reason;
  final String? eligibilityType;
  bool get verified => decision == 'VERIFIED';
}

class VerificationRecord {
  const VerificationRecord({
    this.id,
    required this.time,
    required this.studentNumber,
    this.studentNumberHash,
    required this.fullName,
    this.program = '',
    required this.status,
    required this.score,
    this.capturedImagePath,
    this.storedImagePath,
    this.mode = 'Offline verification',
    this.previousHash,
    this.logHash,
  });

  final int? id;
  final DateTime time;
  final String studentNumber;
  final String? studentNumberHash;
  final String fullName;
  final String program;
  final VerificationStatus status;
  final double score;
  final String? capturedImagePath;
  final String? storedImagePath;
  final String mode;
  final String? previousHash;
  final String? logHash;

  String get studentNumberHashShort =>
      (studentNumberHash ?? AuthService.hashIdentifier(studentNumber))
          .substring(0, 16);

  String get programLabel =>
      program.trim().isEmpty ? 'Program not recorded' : program.trim();

  String get timeLabel {
    final month = time.month.toString().padLeft(2, '0');
    final day = time.day.toString().padLeft(2, '0');
    final hour = time.hour.toString().padLeft(2, '0');
    final minute = time.minute.toString().padLeft(2, '0');
    return '${time.year}-$month-$day $hour:$minute';
  }

  Map<String, Object?> toMap() {
    return {
      'student_number': studentNumber,
      'student_number_hash':
          studentNumberHash ?? AuthService.hashIdentifier(studentNumber),
      'full_name': fullName,
      'program': program,
      'status': status.name,
      'score': score,
      'captured_image_path': capturedImagePath,
      'stored_image_path': storedImagePath,
      'mode': mode,
      'verified_at': time.toIso8601String(),
      'previous_hash': previousHash,
      'log_hash': logHash,
    };
  }

  static VerificationRecord fromMap(Map<String, Object?> map) {
    return VerificationRecord(
      id: map['id'] as int?,
      time: DateTime.parse(map['verified_at'] as String),
      studentNumber: map['student_number'] as String,
      studentNumberHash:
          map['student_number_hash'] as String? ??
          AuthService.hashIdentifier(map['student_number'] as String),
      fullName: map['full_name'] as String,
      program: (map['program'] as String?) ?? '',
      status: VerificationStatus.values.firstWhere(
        (status) => status.name == map['status'],
        orElse: () => VerificationStatus.notVerified,
      ),
      score: (map['score'] as num?)?.toDouble() ?? 1,
      capturedImagePath: map['captured_image_path'] as String?,
      storedImagePath: map['stored_image_path'] as String?,
      mode: (map['mode'] as String?) ?? 'Offline verification',
      previousHash: map['previous_hash'] as String?,
      logHash: map['log_hash'] as String?,
    );
  }

  static VerificationRecord fromApi(Map<String, dynamic> map) {
    final number =
        (map['student_number'] as String?) ??
        (map['student_number_mask'] as String?) ??
        'UNKNOWN';
    final metadata =
        map['metadata'] as Map<String, dynamic>? ?? const <String, dynamic>{};
    return VerificationRecord(
      id: map['id'] as int?,
      time:
          DateTime.tryParse(
            (map['verified_at'] as String?) ??
                (map['created_at'] as String?) ??
                '',
          ) ??
          DateTime.now(),
      studentNumber: number,
      studentNumberHash:
          map['student_number_hash'] as String? ??
          AuthService.hashIdentifier(number),
      fullName: (map['full_name'] as String?) ?? 'Unknown student',
      program: (map['program'] as String?) ?? '',
      status: VerificationStatus.values.firstWhere(
        (status) =>
            status.name == map['status'] ||
            status.label == map['result'] ||
            status.label == map['status'],
        orElse: () =>
            (map['status'] == 'VERIFIED' || map['result'] == 'VERIFIED')
            ? VerificationStatus.verified
            : map['status'] == 'SPOOF_DETECTED'
            ? VerificationStatus.spoofDetected
            : VerificationStatus.notVerified,
      ),
      score:
          (map['score'] as num?)?.toDouble() ??
          (map['confidence'] as num?)?.toDouble() ??
          0,
      capturedImagePath:
          (map['captured_image_path'] as String?) ??
          metadata['captured_image_path'] as String?,
      storedImagePath:
          (map['stored_image_path'] as String?) ??
          metadata['stored_image_path'] as String?,
      mode:
          (map['backend'] as String?) ??
          (map['mode'] as String?) ??
          metadata['mode'] as String? ??
          'Online',
      previousHash: map['previous_log_hash'] as String?,
      logHash: map['log_hash'] as String?,
    );
  }

  VerificationRecord withAudit({
    required String previousHash,
    required String logHash,
  }) {
    return VerificationRecord(
      id: id,
      time: time,
      studentNumber: studentNumber,
      studentNumberHash:
          studentNumberHash ?? AuthService.hashIdentifier(studentNumber),
      fullName: fullName,
      program: program,
      status: status,
      score: score,
      capturedImagePath: capturedImagePath,
      storedImagePath: storedImagePath,
      mode: mode,
      previousHash: previousHash,
      logHash: logHash,
    );
  }

  VerificationRecord withStudentContext(StudentRecord? student) {
    if (student == null) return this;
    return VerificationRecord(
      id: id,
      time: time,
      studentNumber: studentNumber,
      studentNumberHash:
          studentNumberHash ??
          AuthService.hashIdentifier(student.studentNumber),
      fullName: fullName,
      program: program.trim().isEmpty ? student.program : program,
      status: status,
      score: score,
      capturedImagePath: capturedImagePath,
      storedImagePath: (storedImagePath == null || storedImagePath!.isEmpty)
          ? student.photoPath
          : storedImagePath,
      mode: mode,
      previousHash: previousHash,
      logHash: logHash,
    );
  }
}

class AuditSummary {
  const AuditSummary({
    required this.total,
    required this.checked,
    required this.unsigned,
    required this.tampered,
  });

  final int total;
  final int checked;
  final int unsigned;
  final int tampered;

  static AuditSummary fromLogs(List<VerificationRecord> logs) {
    final ordered = [...logs]
      ..sort((a, b) {
        final idA = a.id ?? 0;
        final idB = b.id ?? 0;
        if (idA != idB) return idA.compareTo(idB);
        return a.time.compareTo(b.time);
      });
    var checked = 0;
    var unsigned = 0;
    var tampered = 0;
    var previousHash = 'GENESIS';
    for (final log in ordered) {
      if (log.previousHash == null || log.logHash == null) {
        unsigned += 1;
        continue;
      }
      checked += 1;
      final expected = auditChecksum(log, previousHash);
      if (log.previousHash != previousHash || log.logHash != expected) {
        tampered += 1;
      }
      previousHash = log.logHash!;
    }
    return AuditSummary(
      total: logs.length,
      checked: checked,
      unsigned: unsigned,
      tampered: tampered,
    );
  }
}

String auditChecksum(VerificationRecord record, String previousHash) {
  final payload = [
    record.studentNumber,
    record.fullName,
    record.status.name,
    record.score.toStringAsFixed(8),
    record.capturedImagePath ?? '',
    record.mode,
    record.time.toIso8601String(),
    previousHash,
  ].join('|');
  var hash = 2166136261;
  for (final unit in payload.codeUnits) {
    hash ^= unit;
    hash = (hash * 16777619) & 0xffffffff;
  }
  return hash.toRadixString(16).padLeft(8, '0');
}

class AdminAccessRequestDraft {
  const AdminAccessRequestDraft({
    required this.fullName,
    required this.email,
    required this.username,
    required this.phoneNumber,
    required this.department,
    required this.requestedRole,
    required this.note,
  });

  final String fullName;
  final String email;
  final String username;
  final String phoneNumber;
  final String department;
  final String requestedRole;
  final String note;

  Map<String, Object?> toJson() {
    return {
      'full_name': fullName,
      'email': email,
      'username': username,
      'phone_number': phoneNumber,
      'department': department,
      'requested_role': requestedRole,
      'note': note,
    };
  }
}

class AdminAccessRequest {
  const AdminAccessRequest({
    required this.id,
    required this.fullName,
    required this.email,
    required this.username,
    required this.phoneNumber,
    required this.department,
    required this.requestedRole,
    required this.status,
    required this.note,
    required this.createdAt,
  });

  final int id;
  final String fullName;
  final String email;
  final String username;
  final String phoneNumber;
  final String department;
  final String requestedRole;
  final String status;
  final String note;
  final DateTime createdAt;

  Color get statusColor {
    return switch (status) {
      'approved' => AppColors.green,
      'rejected' => AppColors.red,
      _ => AppColors.amber,
    };
  }

  static AdminAccessRequest fromApi(Map<String, dynamic> map) {
    return AdminAccessRequest(
      id: map['id'] as int,
      fullName: (map['full_name'] as String?) ?? 'Unknown requester',
      email: (map['email'] as String?) ?? '',
      username: (map['username'] as String?) ?? '',
      phoneNumber: (map['phone_number'] as String?) ?? '',
      department: (map['department'] as String?) ?? '',
      requestedRole: (map['requested_role'] as String?) ?? 'Invigilator',
      status: (map['status'] as String?) ?? 'pending',
      note: (map['note'] as String?) ?? '',
      createdAt:
          DateTime.tryParse((map['created_at'] as String?) ?? '') ??
          DateTime.now(),
    );
  }
}

enum VerificationStatus {
  verified('VERIFIED'),
  notVerified('NOT VERIFIED'),
  spoofDetected('SPOOF DETECTED');

  const VerificationStatus(this.label);
  final String label;
}

class ExamVerifyStore {
  static bool _ffiReady = false;
  Database? _database;

  Future<Database> get database async {
    if (_database != null) return _database!;
    if (!Platform.isAndroid && !Platform.isIOS && !_ffiReady) {
      sqfliteFfiInit();
      databaseFactory = databaseFactoryFfi;
      _ffiReady = true;
    }
    final dbDirectory = await getDatabasesPath();
    final dbPath = '$dbDirectory${Platform.pathSeparator}examverify_mobile.db';
    _database = await openDatabase(
      dbPath,
      version: 1,
      onCreate: (db, version) async {
        await db.execute('''
          CREATE TABLE students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_number TEXT NOT NULL UNIQUE,
            student_number_hash TEXT,
            full_name TEXT NOT NULL,
            program TEXT NOT NULL,
            level TEXT NOT NULL DEFAULT '',
            student_status TEXT NOT NULL DEFAULT 'active',
            eligible INTEGER NOT NULL,
            note TEXT NOT NULL,
            photo_path TEXT NOT NULL,
            signature_json TEXT NOT NULL,
            backend_embedding TEXT,
            backend_name TEXT,
            created_at TEXT NOT NULL
          )
        ''');
        await db.execute('''
          CREATE TABLE verification_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_number TEXT NOT NULL,
            student_number_hash TEXT,
            full_name TEXT NOT NULL,
            program TEXT,
            status TEXT NOT NULL,
            score REAL NOT NULL,
            captured_image_path TEXT,
            stored_image_path TEXT,
            mode TEXT NOT NULL,
            verified_at TEXT NOT NULL,
            previous_hash TEXT,
            log_hash TEXT
          )
        ''');
        await db.execute('''
          CREATE TABLE deleted_students (
            student_number_hash TEXT PRIMARY KEY,
            deleted_at TEXT NOT NULL
          )
        ''');
        await _createExamSessionTables(db);
      },
    );
    await _ensureColumns(_database!);
    return _database!;
  }

  Future<void> _ensureColumns(Database db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS deleted_students (
        student_number_hash TEXT PRIMARY KEY,
        deleted_at TEXT NOT NULL
      )
    ''');
    await _createExamSessionTables(db);
    final studentColumns = await db.rawQuery('PRAGMA table_info(students)');
    final studentExisting = studentColumns
        .map((row) => row['name'] as String)
        .toSet();
    if (!studentExisting.contains('backend_embedding')) {
      await db.execute(
        'ALTER TABLE students ADD COLUMN backend_embedding TEXT',
      );
    }
    if (!studentExisting.contains('backend_name')) {
      await db.execute('ALTER TABLE students ADD COLUMN backend_name TEXT');
    }
    if (!studentExisting.contains('student_number_hash')) {
      await db.execute(
        'ALTER TABLE students ADD COLUMN student_number_hash TEXT',
      );
      final rows = await db.query(
        'students',
        columns: ['id', 'student_number'],
      );
      for (final row in rows) {
        await db.update(
          'students',
          {
            'student_number_hash': AuthService.hashIdentifier(
              row['student_number'] as String,
            ),
          },
          where: 'id = ?',
          whereArgs: [row['id']],
        );
      }
    }
    if (!studentExisting.contains('level')) {
      await db.execute(
        "ALTER TABLE students ADD COLUMN level TEXT NOT NULL DEFAULT ''",
      );
    }
    if (!studentExisting.contains('student_status')) {
      await db.execute(
        "ALTER TABLE students ADD COLUMN student_status TEXT NOT NULL DEFAULT 'active'",
      );
    }
    final logColumns = await db.rawQuery(
      'PRAGMA table_info(verification_logs)',
    );
    final logExisting = logColumns.map((row) => row['name'] as String).toSet();
    if (!logExisting.contains('previous_hash')) {
      await db.execute(
        'ALTER TABLE verification_logs ADD COLUMN previous_hash TEXT',
      );
    }
    if (!logExisting.contains('log_hash')) {
      await db.execute(
        'ALTER TABLE verification_logs ADD COLUMN log_hash TEXT',
      );
    }
    if (!logExisting.contains('program')) {
      await db.execute('ALTER TABLE verification_logs ADD COLUMN program TEXT');
    }
    if (!logExisting.contains('stored_image_path')) {
      await db.execute(
        'ALTER TABLE verification_logs ADD COLUMN stored_image_path TEXT',
      );
    }
    if (!logExisting.contains('student_number_hash')) {
      await db.execute(
        'ALTER TABLE verification_logs ADD COLUMN student_number_hash TEXT',
      );
      final rows = await db.query(
        'verification_logs',
        columns: ['id', 'student_number'],
      );
      for (final row in rows) {
        await db.update(
          'verification_logs',
          {
            'student_number_hash': AuthService.hashIdentifier(
              row['student_number'] as String,
            ),
          },
          where: 'id = ?',
          whereArgs: [row['id']],
        );
      }
    }
  }

  static Future<void> _createExamSessionTables(DatabaseExecutor db) async {
    await db.execute('''
      CREATE TABLE IF NOT EXISTS exam_sessions (
        id INTEGER PRIMARY KEY,
        course_code TEXT NOT NULL,
        course_name TEXT NOT NULL,
        program TEXT NOT NULL,
        level TEXT NOT NULL,
        exam_date TEXT NOT NULL,
        start_time TEXT NOT NULL,
        end_time TEXT NOT NULL,
        venue TEXT NOT NULL,
        status TEXT NOT NULL
      )
    ''');
    await db.execute('''
      CREATE TABLE IF NOT EXISTS exam_session_students (
        id INTEGER PRIMARY KEY,
        exam_session_id INTEGER NOT NULL,
        student_id INTEGER NOT NULL,
        eligibility_type TEXT NOT NULL,
        eligibility_status TEXT NOT NULL,
        attendance_status TEXT NOT NULL,
        verified_at TEXT
      )
    ''');
  }

  Future<List<StudentRecord>> listStudents() async {
    final db = await database;
    final rows = await db.query(
      'students',
      orderBy: 'full_name COLLATE NOCASE',
    );
    return rows.map(StudentRecord.fromMap).toList();
  }

  Future<void> upsertStudent(StudentRecord student) async {
    final db = await database;
    await db.insert(
      'students',
      student.toMap(),
      conflictAlgorithm: ConflictAlgorithm.replace,
    );
  }

  Future<void> replaceStudents(List<StudentRecord> students) async {
    final db = await database;
    await db.transaction((txn) async {
      await txn.delete('students');
      for (final student in students) {
        await txn.insert(
          'students',
          student.toMap(),
          conflictAlgorithm: ConflictAlgorithm.replace,
        );
      }
    });
  }

  Future<void> deleteStudent(StudentRecord student) async {
    final db = await database;
    final hash =
        student.studentNumberHash ??
        AuthService.hashIdentifier(student.studentNumber);
    await db.insert('deleted_students', {
      'student_number_hash': hash,
      'deleted_at': DateTime.now().toIso8601String(),
    }, conflictAlgorithm: ConflictAlgorithm.replace);
    await db.delete(
      'students',
      where: 'student_number_hash = ? OR student_number = ?',
      whereArgs: [hash, student.studentNumber],
    );
    if (student.photoPath.isNotEmpty) {
      final photo = File(student.photoPath);
      if (await photo.exists()) {
        await photo.delete();
      }
    }
  }

  Future<Set<String>> listDeletedStudentHashes() async {
    final db = await database;
    final rows = await db.query('deleted_students');
    return rows.map((row) => row['student_number_hash'] as String).toSet();
  }

  Future<void> clearStudentDeletion(String studentNumberHash) async {
    final db = await database;
    await db.delete(
      'deleted_students',
      where: 'student_number_hash = ?',
      whereArgs: [studentNumberHash],
    );
  }

  Future<List<VerificationRecord>> listLogs() async {
    final db = await database;
    final rows = await db.query(
      'verification_logs',
      orderBy: 'verified_at DESC',
      limit: 100,
    );
    return rows.map(VerificationRecord.fromMap).toList();
  }

  Future<void> addLog(VerificationRecord record) async {
    final db = await database;
    final previous = await db.rawQuery(
      'SELECT log_hash FROM verification_logs WHERE log_hash IS NOT NULL ORDER BY id DESC LIMIT 1',
    );
    final previousHash = previous.isEmpty
        ? 'GENESIS'
        : previous.first['log_hash'] as String? ?? 'GENESIS';
    final signedRecord = record.withAudit(
      previousHash: previousHash,
      logHash: auditChecksum(record, previousHash),
    );
    await db.insert('verification_logs', signedRecord.toMap());
  }

  Future<void> clearLogs() async {
    final db = await database;
    await db.delete('verification_logs');
  }

  Future<List<ExamSessionRecord>> listExamSessions() async {
    final db = await database;
    final rows = await db.query('exam_sessions', orderBy: 'exam_date DESC');
    return rows.map(ExamSessionRecord.fromMap).toList();
  }

  Future<void> replaceExamSessions(List<ExamSessionRecord> rows) async {
    final db = await database;
    await db.transaction((txn) async {
      await txn.delete('exam_sessions');
      for (final row in rows) {
        await txn.insert('exam_sessions', row.toMap());
      }
    });
  }

  Future<List<ExamEligibilityRecord>> listExamEligibilities() async {
    final db = await database;
    final rows = await db.query('exam_session_students');
    return rows.map(ExamEligibilityRecord.fromMap).toList();
  }

  Future<void> replaceExamEligibilities(
    List<ExamEligibilityRecord> rows,
  ) async {
    final db = await database;
    await db.transaction((txn) async {
      await txn.delete('exam_session_students');
      for (final row in rows) {
        await txn.insert('exam_session_students', row.toMap());
      }
    });
  }
}

class ExamVerifyFiles {
  static Future<File> saveStudentPhoto(
    File source,
    String studentNumber,
    String purpose,
  ) async {
    final directory = await getApplicationDocumentsDirectory();
    final imageDirectory = Directory(
      '${directory.path}${Platform.pathSeparator}examverify_images',
    );
    if (!await imageDirectory.exists()) {
      await imageDirectory.create(recursive: true);
    }
    final safeNumber = studentNumber.replaceAll(RegExp(r'[^A-Za-z0-9_-]'), '_');
    final timestamp = DateTime.now().millisecondsSinceEpoch;
    final destination = File(
      '${imageDirectory.path}${Platform.pathSeparator}${safeNumber}_${purpose}_$timestamp.jpg',
    );
    return source.copy(destination.path);
  }
}

class MobileLivenessResult {
  const MobileLivenessResult({
    required this.passed,
    required this.message,
    required this.score,
  });

  final bool passed;
  final String message;
  final double score;
}

class FaceEngine {
  static const verificationThreshold = 0.28;
  static const verificationMinimumGap = 0.06;
  static const identificationThreshold = 0.30;
  static const identificationMinimumGap = 0.08;

  static String get signatureBackend => Platform.isAndroid || Platform.isIOS
      ? 'MobileFaceNet TFLite'
      : Platform.isWindows
      ? 'MobileFaceNet TFLite / Desktop runtime'
      : 'Device visual signature';

  static Future<FaceSignal> analyzeFaceSignal(File imageFile) async {
    if (Platform.isWindows) {
      final backendSignal = await PythonFaceBackend.analyzeLiveness(
        imageFile.path,
      );
      if (backendSignal != null) return backendSignal;
      return const FaceSignal(
        faceCount: 0,
        quality: 0,
        yaw: 0,
        pitch: 0,
        roll: 0,
        leftEyeOpen: 0,
        rightEyeOpen: 0,
        poseReliable: false,
        message: 'Desktop face engine is not available.',
      );
    }

    if (!Platform.isAndroid && !Platform.isIOS) {
      final bytes = await imageFile.readAsBytes();
      final decoded = imglib.decodeImage(bytes);
      if (decoded == null) {
        return const FaceSignal(
          faceCount: 0,
          quality: 0,
          yaw: 0,
          pitch: 0,
          roll: 0,
          leftEyeOpen: 0.5,
          rightEyeOpen: 0.5,
          poseReliable: false,
          message: 'Image could not be decoded.',
        );
      }
      final brightness = _averageBrightness(imglib.bakeOrientation(decoded));
      return FaceSignal(
        faceCount: brightness > 0.10 ? 1 : 0,
        quality: brightness.clamp(0.0, 1.0),
        yaw: 0,
        pitch: 0,
        roll: 0,
        leftEyeOpen: 0.8,
        rightEyeOpen: 0.8,
        poseReliable: false,
        message: brightness > 0.10
            ? 'Desktop visual signal locked.'
            : 'Camera image is too dark.',
      );
    }

    final detector = FaceDetector(
      options: FaceDetectorOptions(
        performanceMode: FaceDetectorMode.accurate,
        enableClassification: true,
        enableContours: true,
        enableLandmarks: true,
      ),
    );
    try {
      final faces = await detector.processImage(
        InputImage.fromFilePath(imageFile.path),
      );
      if (faces.length != 1) {
        return FaceSignal(
          faceCount: faces.length,
          quality: 0,
          yaw: 0,
          pitch: 0,
          roll: 0,
          leftEyeOpen: 0.5,
          rightEyeOpen: 0.5,
          poseReliable: true,
          message: faces.isEmpty
              ? 'Searching for a face...'
              : 'Multiple faces detected. Keep only one face in frame.',
        );
      }
      final face = faces.first;
      final box = face.boundingBox;
      final areaScore = ((box.width * box.height) / (900 * 900)).clamp(
        0.0,
        1.0,
      );
      final leftEye =
          face.leftEyeOpenProbability ??
          _eyeOpenFromContour(face, FaceContourType.leftEye) ??
          0.5;
      final rightEye =
          face.rightEyeOpenProbability ??
          _eyeOpenFromContour(face, FaceContourType.rightEye) ??
          0.5;
      final yaw = face.headEulerAngleY ?? 0;
      final pitch = face.headEulerAngleX ?? 0;
      final roll = face.headEulerAngleZ ?? 0;
      final poseScore =
          1 - ((yaw.abs() + pitch.abs() + roll.abs()) / 110).clamp(0.0, 1.0);
      final eyeScore = ((leftEye + rightEye) / 2).clamp(0.0, 1.0);
      final geometryScore = _contourGeometryScore(face);
      final quality =
          (areaScore * 0.22) +
          (poseScore * 0.24) +
          (eyeScore * 0.20) +
          (geometryScore * 0.34);
      return FaceSignal(
        faceCount: 1,
        quality: quality.clamp(0.0, 1.0),
        yaw: yaw,
        pitch: pitch,
        roll: roll,
        leftEyeOpen: leftEye,
        rightEyeOpen: rightEye,
        poseReliable: true,
        message: 'Face mesh and liveness signal locked.',
      );
    } finally {
      detector.close();
    }
  }

  static Future<List<double>> createSignature(File imageFile) async {
    if (Platform.isWindows) {
      return PythonFaceBackend.createMobileSignature(imageFile.path);
    }
    if (!Platform.isAndroid && !Platform.isIOS) {
      final bytes = await imageFile.readAsBytes();
      final decoded = imglib.decodeImage(bytes);
      if (decoded == null) {
        throw FaceEngineException('The selected image could not be decoded.');
      }
      return _signatureFromImage(imglib.bakeOrientation(decoded));
    }

    final detector = FaceDetector(
      options: FaceDetectorOptions(
        performanceMode: FaceDetectorMode.accurate,
        enableClassification: false,
        enableContours: false,
        enableLandmarks: false,
      ),
    );
    try {
      final faces = await detector.processImage(
        InputImage.fromFilePath(imageFile.path),
      );
      if (faces.isEmpty) {
        throw FaceEngineException(
          'No face was detected. Use a clear front-facing photo with good lighting.',
        );
      }
      faces.sort((a, b) {
        final areaA = a.boundingBox.width * a.boundingBox.height;
        final areaB = b.boundingBox.width * b.boundingBox.height;
        return areaB.compareTo(areaA);
      });

      final bytes = await imageFile.readAsBytes();
      final decoded = imglib.decodeImage(bytes);
      if (decoded == null) {
        throw FaceEngineException('The selected image could not be decoded.');
      }
      final oriented = imglib.bakeOrientation(decoded);
      final box = faces.first.boundingBox;
      final padX = (box.width * 0.20).round();
      final padTop = (box.height * 0.25).round();
      final padBottom = (box.height * 0.18).round();
      final left = (box.left.floor() - padX).clamp(0, oriented.width - 1);
      final top = (box.top.floor() - padTop).clamp(0, oriented.height - 1);
      final right = (box.right.ceil() + padX).clamp(left + 1, oriented.width);
      final bottom = (box.bottom.ceil() + padBottom).clamp(
        top + 1,
        oriented.height,
      );
      final cropped = imglib.copyCrop(
        oriented,
        x: left,
        y: top,
        width: right - left,
        height: bottom - top,
      );
      return MobileFaceEmbeddingEngine.createEmbedding(cropped);
    } finally {
      detector.close();
    }
  }

  static Future<MobileLivenessResult> checkLiveness(File imageFile) async {
    if (Platform.isWindows) {
      final faceSignal = await analyzeFaceSignal(imageFile);
      final eyesOpen =
          ((faceSignal.leftEyeOpen + faceSignal.rightEyeOpen) / 2) > 0.34;
      final passed =
          faceSignal.faceCount == 1 &&
          faceSignal.poseReliable &&
          faceSignal.quality >= 0.62 &&
          faceSignal.yaw.abs() <= 14 &&
          faceSignal.pitch.abs() <= 14 &&
          faceSignal.roll.abs() <= 14 &&
          eyesOpen;
      return MobileLivenessResult(
        passed: passed,
        message: passed
            ? 'Desktop liveness and pose checks passed.'
            : 'Desktop liveness needs one clear centered face with stable low-light quality.',
        score: faceSignal.quality,
      );
    }
    if (!Platform.isAndroid && !Platform.isIOS) {
      final bytes = await imageFile.readAsBytes();
      final decoded = imglib.decodeImage(bytes);
      if (decoded == null) {
        return const MobileLivenessResult(
          passed: false,
          message: 'Image could not be decoded.',
          score: 0,
        );
      }
      final brightness = _averageBrightness(imglib.bakeOrientation(decoded));
      return MobileLivenessResult(
        passed: brightness > 0.12,
        message: brightness > 0.12
            ? 'Desktop liveness pre-check passed.'
            : 'Image is too dark for liveness verification.',
        score: brightness,
      );
    }

    final detector = FaceDetector(
      options: FaceDetectorOptions(
        performanceMode: FaceDetectorMode.accurate,
        enableClassification: true,
        enableContours: true,
        enableLandmarks: true,
      ),
    );
    try {
      final faces = await detector.processImage(
        InputImage.fromFilePath(imageFile.path),
      );
      if (faces.length != 1) {
        return MobileLivenessResult(
          passed: false,
          message: faces.isEmpty
              ? 'No live face was detected.'
              : 'Multiple faces detected. Verify one student at a time.',
          score: 0,
        );
      }
      final face = faces.first;
      final leftEye =
          face.leftEyeOpenProbability ??
          _eyeOpenFromContour(face, FaceContourType.leftEye) ??
          0.5;
      final rightEye =
          face.rightEyeOpenProbability ??
          _eyeOpenFromContour(face, FaceContourType.rightEye) ??
          0.5;
      final yaw = (face.headEulerAngleY ?? 0).abs();
      final roll = (face.headEulerAngleZ ?? 0).abs();
      final trackingScore = ((leftEye + rightEye) / 2).clamp(0.0, 1.0);
      final poseScore = (1 - ((yaw + roll) / 90)).clamp(0.0, 1.0);
      final score = (trackingScore * 0.55) + (poseScore * 0.45);
      final passed = score >= 0.42 && yaw <= 36 && roll <= 28;
      return MobileLivenessResult(
        passed: passed,
        message: passed
            ? 'Mobile liveness pre-check passed.'
            : 'Face pose or eye signal is not strong enough for liveness.',
        score: score,
      );
    } finally {
      detector.close();
    }
  }

  static double _averageBrightness(imglib.Image image) {
    final resized = imglib.copyResize(image, width: 24, height: 24);
    var total = 0.0;
    for (var y = 0; y < resized.height; y++) {
      for (var x = 0; x < resized.width; x++) {
        final pixel = resized.getPixel(x, y);
        total += (0.299 * pixel.r + 0.587 * pixel.g + 0.114 * pixel.b) / 255.0;
      }
    }
    return total / (resized.width * resized.height);
  }

  static double? _eyeOpenFromContour(Face face, FaceContourType type) {
    final points = face.contours[type]?.points;
    if (points == null || points.length < 6) return null;
    var minX = points.first.x.toDouble();
    var maxX = minX;
    var minY = points.first.y.toDouble();
    var maxY = minY;
    for (final point in points.skip(1)) {
      final x = point.x.toDouble();
      final y = point.y.toDouble();
      if (x < minX) minX = x;
      if (x > maxX) maxX = x;
      if (y < minY) minY = y;
      if (y > maxY) maxY = y;
    }
    final width = math.max(1.0, maxX - minX);
    final height = math.max(0.0, maxY - minY);
    final ear = height / width;
    return ((ear - 0.08) / 0.18).clamp(0.0, 1.0);
  }

  static double _contourGeometryScore(Face face) {
    final contourPoints = face.contours.values.fold<int>(
      0,
      (total, contour) => total + (contour?.points.length ?? 0),
    );
    final landmarkPoints = face.landmarks.values
        .where((landmark) => landmark != null)
        .length;
    final contourScore = (contourPoints / 110).clamp(0.0, 1.0);
    final landmarkScore = (landmarkPoints / 8).clamp(0.0, 1.0);
    return (contourScore * 0.72) + (landmarkScore * 0.28);
  }

  static List<double> _signatureFromImage(imglib.Image source) {
    final resized = imglib.copyResize(source, width: 32, height: 32);
    final raw = <double>[];
    for (var y = 0; y < resized.height; y++) {
      for (var x = 0; x < resized.width; x++) {
        final pixel = resized.getPixel(x, y);
        final luminance =
            (0.299 * pixel.r + 0.587 * pixel.g + 0.114 * pixel.b) / 255.0;
        raw.add(luminance);
      }
    }
    final mean = raw.reduce((a, b) => a + b) / raw.length;
    final variance =
        raw.map((value) => math.pow(value - mean, 2)).reduce((a, b) => a + b) /
        raw.length;
    final deviation = math.sqrt(variance).clamp(0.0001, double.infinity);
    return raw.map((value) => (value - mean) / deviation).toList();
  }

  static double distance(List<double> reference, List<double> live) {
    final length = math.min(reference.length, live.length);
    if (length == 0) return 1;
    double dot = 0;
    double referenceNorm = 0;
    double liveNorm = 0;
    for (var index = 0; index < length; index++) {
      dot += reference[index] * live[index];
      referenceNorm += reference[index] * reference[index];
      liveNorm += live[index] * live[index];
    }
    final denominator = math.sqrt(referenceNorm) * math.sqrt(liveNorm);
    if (denominator == 0) return 1;
    final cosine = (dot / denominator).clamp(-1.0, 1.0);
    return (1 - cosine) / 2;
  }

  static bool canCompareSignatures(List<double> reference, List<double> live) {
    if (reference.isEmpty || live.isEmpty || reference.length != live.length) {
      return false;
    }
    if (Platform.isAndroid || Platform.isIOS || Platform.isWindows) {
      return live.length == MobileFaceEmbeddingEngine.embeddingSize;
    }
    return true;
  }
}

class MobileFaceEmbeddingEngine {
  static const int inputSize = 112;
  static const int embeddingSize = 192;
  static tfl.Interpreter? _interpreter;

  static Future<List<double>> createEmbedding(imglib.Image face) async {
    final interpreter = _interpreter ??= await tfl.Interpreter.fromAsset(
      'assets/models/mobilefacenet.tflite',
    );
    final balancedFace = _balanceLowLight(face);
    final resized = imglib.copyResize(
      balancedFace,
      width: inputSize,
      height: inputSize,
    );
    final input = [
      [
        for (var y = 0; y < inputSize; y++)
          [
            for (var x = 0; x < inputSize; x++)
              [
                (resized.getPixel(x, y).r.toDouble() - 127.5) / 128.0,
                (resized.getPixel(x, y).g.toDouble() - 127.5) / 128.0,
                (resized.getPixel(x, y).b.toDouble() - 127.5) / 128.0,
              ],
          ],
      ],
    ];
    final output = [List<double>.filled(embeddingSize, 0)];
    interpreter.run(input, output);
    final raw = output.first;
    final norm = math.sqrt(
      raw.map((value) => value * value).fold<double>(0, (a, b) => a + b),
    );
    if (norm == 0) {
      throw FaceEngineException('Could not generate a biometric embedding.');
    }
    return raw.map((value) => value / norm).toList();
  }

  static imglib.Image _balanceLowLight(imglib.Image face) {
    final brightness = FaceEngine._averageBrightness(face);
    if (brightness >= 0.42) return face;

    final balanced = imglib.Image.from(face);
    final strength = ((0.42 - brightness) / 0.42).clamp(0.0, 1.0);
    final gamma = 1.0 - (0.28 * strength);
    final lift = 18.0 * strength;
    final contrast = 1.0 + (0.18 * strength);

    int channel(num value) {
      final normalized = (value / 255.0).clamp(0.0, 1.0);
      final corrected = math.pow(normalized, gamma).toDouble() * 255.0;
      final contrasted = ((corrected - 128.0) * contrast) + 128.0 + lift;
      return contrasted.round().clamp(0, 255);
    }

    for (var y = 0; y < balanced.height; y++) {
      for (var x = 0; x < balanced.width; x++) {
        final pixel = balanced.getPixel(x, y);
        balanced.setPixelRgb(
          x,
          y,
          channel(pixel.r),
          channel(pixel.g),
          channel(pixel.b),
        );
      }
    }
    return balanced;
  }
}

class FaceEngineException implements Exception {
  FaceEngineException(this.message);
  final String message;

  @override
  String toString() => message;
}

class OnlineBackendClient {
  const OnlineBackendClient({required this.baseUrl, this.token});

  final String baseUrl;
  final String? token;

  Uri _uri(String path) =>
      Uri.parse('${baseUrl.replaceAll(RegExp(r"/+$"), '')}$path');

  Map<String, String> get _headers => {
    'Content-Type': 'application/json',
    if (token != null) 'Authorization': 'Bearer $token',
  };

  Future<void> healthCheck() async {
    await _getJson('/health');
  }

  Future<Map<String, dynamic>> requestOtp(
    String username,
    String password, {
    required String requestedRole,
  }) {
    return _postJson('/auth/login', {
      'username': username,
      'password': password,
      'requested_role': requestedRole,
    });
  }

  Future<AuthUser> verifyOtp(String username, String otp) async {
    final response = await _postJson('/auth/verify-otp', {
      'username': username,
      'otp': otp,
    });
    final user = response['user'] as Map<String, dynamic>;
    return AuthUser(
      username: user['username'] as String,
      fullName: user['full_name'] as String,
      role: user['role'] as String,
      token: response['access_token'] as String? ?? response['token'] as String,
      backendUrl: baseUrl,
    );
  }

  Future<List<StudentRecord>> listStudents() async {
    final response = await _getJson('/students');
    final rows = response['students'] as List;
    return [
      for (final row in rows)
        StudentRecord.fromApi(row as Map<String, dynamic>),
    ];
  }

  Future<List<VerificationRecord>> listLogs() async {
    final response = await _getJson('/verification/logs');
    final rows = response['logs'] as List;
    return [
      for (final row in rows)
        VerificationRecord.fromApi(row as Map<String, dynamic>),
    ];
  }

  static bool isPortablePortrait(String path) => path.startsWith('data:image/');

  Future<void> registerStudent(StudentRecord student) async {
    final portablePortrait = await _portablePortrait(student.photoPath);
    await _postJson('/students/sync', {
      'student_number_hash':
          student.studentNumberHash ??
          AuthService.hashIdentifier(student.studentNumber),
      'student_number_mask': AuthService.maskIdentifier(student.studentNumber),
      'full_name': student.fullName,
      'program': student.program,
      'level': student.level,
      'status': student.status,
      'photo_url': portablePortrait,
      'biometric_profile': {
        'signature': student.signature,
        'embedding_backend': student.backendName ?? 'device_signature',
        'enrollment_version': 1,
      },
    });
  }

  Future<String> _portablePortrait(String source) async {
    if (isPortablePortrait(source) ||
        source.startsWith('http://') ||
        source.startsWith('https://')) {
      return source;
    }
    final file = File(source);
    if (source.isEmpty || !await file.exists()) return source;
    final decoded = imglib.decodeImage(await file.readAsBytes());
    if (decoded == null) return source;
    var portrait = imglib.bakeOrientation(decoded);
    if (portrait.width > 360) {
      portrait = imglib.copyResize(portrait, width: 360);
    }
    final jpeg = imglib.encodeJpg(portrait, quality: 72);
    return 'data:image/jpeg;base64,${base64Encode(jpeg)}';
  }

  Future<void> deleteStudent(StudentRecord student) async {
    final hash =
        student.studentNumberHash ??
        AuthService.hashIdentifier(student.studentNumber);
    await deleteStudentHash(hash);
  }

  Future<void> deleteStudentHash(String hash) async {
    await _deleteJson('/students/$hash');
  }

  Future<void> recordVerification(VerificationRecord record) async {
    await _postJson('/verification/logs', {
      'student_number_mask': AuthService.maskIdentifier(record.studentNumber),
      'full_name': record.fullName,
      'program': record.program,
      'status': switch (record.status) {
        VerificationStatus.verified => 'VERIFIED',
        VerificationStatus.spoofDetected => 'SPOOF_DETECTED',
        VerificationStatus.notVerified => 'UNAUTHORIZED',
      },
      'confidence': record.status == VerificationStatus.verified
          ? (1 - record.score).clamp(0.0, 1.0)
          : record.score,
      'liveness_score': record.status == VerificationStatus.spoofDetected
          ? record.score
          : 1.0,
      'metadata': {
        'mode': record.mode,
        'captured_image_path': record.capturedImagePath,
        'stored_image_path': record.storedImagePath,
        'student_number_hash':
            record.studentNumberHash ??
            AuthService.hashIdentifier(record.studentNumber),
      },
    });
  }

  Future<int> clearVerificationLogs() async {
    Map<String, dynamic> response;
    try {
      response = await _deleteJson('/verification/logs');
    } catch (error) {
      final lower = error.toString().toLowerCase();
      if (!lower.contains('method not allowed') && !lower.contains('405')) {
        rethrow;
      }
      response = await _postJson('/verification/logs/reset', {});
    }
    return (response['deleted'] as num?)?.toInt() ?? 0;
  }

  Future<List<ExamSessionRecord>> listExamSessions() async {
    final response = await _getJson('/exam-sessions');
    final rows = response['exam_sessions'] as List;
    return [
      for (final row in rows)
        ExamSessionRecord.fromMap(row as Map<String, dynamic>),
    ];
  }

  Future<List<ExamEligibilityRecord>> listExamEligibilities(
    int sessionId,
  ) async {
    final response = await _getJson(
      '/exam-sessions/$sessionId/eligible-students',
    );
    final rows = response['eligible_students'] as List;
    return [
      for (final row in rows)
        ExamEligibilityRecord.fromMap(row as Map<String, dynamic>),
    ];
  }

  Future<ExamSessionRecord> createExamSession({
    required String courseCode,
    required String courseName,
    required String program,
    required String level,
    required String examDate,
    required String startTime,
    required String endTime,
    required String venue,
  }) async {
    final response = await _postJson('/exam-sessions', {
      'course_code': courseCode,
      'course_name': courseName,
      'program': program,
      'level': level,
      'exam_date': examDate,
      'start_time': startTime,
      'end_time': endTime,
      'venue': venue,
    });
    return ExamSessionRecord.fromMap(
      response['exam_session'] as Map<String, dynamic>,
    );
  }

  Future<void> activateExamSession(int sessionId) async {
    await _postJson('/exam-sessions/$sessionId/activate', {});
  }

  Future<void> completeExamSession(int sessionId) async {
    await _postJson('/exam-sessions/$sessionId/complete', {});
  }

  Future<void> addExamEligibility({
    required int sessionId,
    required int studentId,
    required String eligibilityType,
  }) async {
    await _postJson('/exam-sessions/$sessionId/eligible-students', {
      'student_id': studentId,
      'eligibility_type': eligibilityType,
      'eligibility_status': 'eligible',
    });
  }

  Future<ExamEntryDecision> evaluateExamEntry({
    required int sessionId,
    required StudentRecord? student,
    required double matchScore,
    required double confidenceGap,
    required double matchThreshold,
    required double minimumConfidenceGap,
    required bool livenessPassed,
    required bool identityMatched,
    required String deviceType,
  }) async {
    final response = await _postJson('/exam-sessions/$sessionId/verify', {
      'detected_student_id': student?.id,
      'match_score': matchScore,
      'confidence_gap': confidenceGap,
      'match_threshold': matchThreshold,
      'minimum_confidence_gap': minimumConfidenceGap,
      'liveness_passed': livenessPassed,
      'identity_matched': identityMatched,
      'device_type': deviceType,
    });
    return ExamEntryDecision(
      decision: response['decision'] as String,
      reason: response['reason'] as String? ?? '',
      eligibilityType: response['eligibility_type'] as String?,
    );
  }

  Future<void> submitAccessRequest(AdminAccessRequestDraft request) async {
    await _postJson('/admin/access-requests', request.toJson());
  }

  Future<List<AdminAccessRequest>> listAdminRequests() async {
    final response = await _getJson('/admin/access-requests');
    final rows = response['requests'] as List;
    return [
      for (final row in rows)
        AdminAccessRequest.fromApi(row as Map<String, dynamic>),
    ];
  }

  Future<void> decideAdminRequest(
    int requestId,
    String status, {
    String? temporaryPassword,
  }) async {
    await _postJson('/admin/access-requests/$requestId/decision', {
      'status': status,
      'temporary_password': ?temporaryPassword,
    });
  }

  Future<VerificationRecord> verifyStudent(
    int studentId,
    File livePhoto,
  ) async {
    final request = http.MultipartRequest('POST', _uri('/verify'));
    request.headers.addAll({
      if (token != null) 'Authorization': 'Bearer $token',
    });
    request.fields['student_id'] = '$studentId';
    request.files.add(
      await http.MultipartFile.fromPath('live_photo', livePhoto.path),
    );
    final response = await _sendMultipart(request);
    final student = response['student'] as Map<String, dynamic>?;
    return VerificationRecord(
      time: DateTime.now(),
      studentNumber: (student?['student_number'] as String?) ?? 'UNKNOWN',
      studentNumberHash: student?['student_number_hash'] as String?,
      fullName: (student?['full_name'] as String?) ?? 'Unknown student',
      program: (student?['program'] as String?) ?? '',
      status: _statusFromApi(response['status'] as String?),
      score: (response['score'] as num?)?.toDouble() ?? 0,
      capturedImagePath: livePhoto.path,
      storedImagePath:
          (student?['photo_path'] as String?) ??
          (student?['photo_url'] as String?),
      mode: (response['backend'] as String?) ?? 'Online verification',
    );
  }

  Future<VerificationRecord> identifyStudent(File livePhoto) async {
    final request = http.MultipartRequest('POST', _uri('/identify'));
    request.headers.addAll({
      if (token != null) 'Authorization': 'Bearer $token',
    });
    request.files.add(
      await http.MultipartFile.fromPath('live_photo', livePhoto.path),
    );
    final response = await _sendMultipart(request);
    final student = response['student'] as Map<String, dynamic>?;
    return VerificationRecord(
      time: DateTime.now(),
      studentNumber: (student?['student_number'] as String?) ?? 'UNKNOWN',
      studentNumberHash: student?['student_number_hash'] as String?,
      fullName:
          (student?['full_name'] as String?) ??
          (response['status'] as String? ?? 'Unknown student'),
      program: (student?['program'] as String?) ?? '',
      status: _statusFromApi(response['status'] as String?),
      score: (response['score'] as num?)?.toDouble() ?? 0,
      capturedImagePath: livePhoto.path,
      storedImagePath:
          (student?['photo_path'] as String?) ??
          (student?['photo_url'] as String?),
      mode: (response['backend'] as String?) ?? 'Online identify',
    );
  }

  VerificationStatus _statusFromApi(String? status) {
    return switch (status) {
      'VERIFIED' => VerificationStatus.verified,
      'SPOOF DETECTED' || 'SPOOF_DETECTED' => VerificationStatus.spoofDetected,
      _ => VerificationStatus.notVerified,
    };
  }

  Future<Map<String, dynamic>> _getJson(String path) async {
    final response = await http.get(_uri(path), headers: _headers);
    return _decode(response.statusCode, response.body);
  }

  Future<Map<String, dynamic>> _postJson(
    String path,
    Map<String, Object?> body,
  ) async {
    final response = await http.post(
      _uri(path),
      headers: _headers,
      body: jsonEncode(body),
    );
    return _decode(response.statusCode, response.body);
  }

  Future<Map<String, dynamic>> _deleteJson(String path) async {
    final response = await http.delete(_uri(path), headers: _headers);
    return _decode(response.statusCode, response.body);
  }

  Future<Map<String, dynamic>> _sendMultipart(
    http.MultipartRequest request,
  ) async {
    final streamed = await request.send();
    final body = await streamed.stream.bytesToString();
    return _decode(streamed.statusCode, body);
  }

  Map<String, dynamic> _decode(int statusCode, String body) {
    final decoded = jsonDecode(body) as Map<String, dynamic>;
    if (statusCode >= 400 || decoded['ok'] != true) {
      final detail = decoded['detail'];
      if (detail is List) {
        throw FaceEngineException(
          'Wrong email/username or password. Please check your details and try again.',
        );
      }
      throw FaceEngineException(
        decoded['error']?.toString() ??
            decoded['message']?.toString() ??
            detail?.toString() ??
            body,
      );
    }
    return decoded;
  }
}

class PythonFaceBackend {
  static const int _port = 8765;
  static Process? _process;

  static Future<bool> get available async {
    if (!Platform.isWindows) return false;
    if (await _health()) return true;
    await _start();
    for (var attempt = 0; attempt < 30; attempt++) {
      if (await _health()) return true;
      await Future<void>.delayed(const Duration(milliseconds: 500));
    }
    return false;
  }

  static Future<BackendEmbedding?> createEmbedding(String imagePath) async {
    if (!await available) return null;
    final response = await _post('/embedding', {'image_path': imagePath});
    return BackendEmbedding(
      embedding: response['embedding'] as String,
      backend: response['backend'] as String,
    );
  }

  static Future<List<double>> createMobileSignature(String imagePath) async {
    if (!await available) {
      throw FaceEngineException(
        'The desktop face service is unavailable. Start the desktop launcher and retry.',
      );
    }
    final response = await _post('/mobilefacenet-signature', {
      'image_path': imagePath,
    });
    final signature = response['signature'];
    if (signature is! List ||
        signature.length != MobileFaceEmbeddingEngine.embeddingSize) {
      throw FaceEngineException(
        'The desktop face service returned an invalid MobileFaceNet signature.',
      );
    }
    return signature.map((value) => (value as num).toDouble()).toList();
  }

  static Future<FaceSignal?> analyzeLiveness(String imagePath) async {
    if (!await available) return null;
    final response = await _post('/liveness', {'image_path': imagePath});
    final faceCount = (response['face_count'] as num?)?.toInt() ?? 0;
    final score = (response['score'] as num?)?.toDouble() ?? 0;
    return FaceSignal(
      faceCount: faceCount,
      quality: score.clamp(0.0, 1.0),
      yaw: (response['yaw'] as num?)?.toDouble() ?? 0,
      pitch: (response['pitch'] as num?)?.toDouble() ?? 0,
      roll: (response['roll'] as num?)?.toDouble() ?? 0,
      leftEyeOpen: (response['left_eye_open'] as num?)?.toDouble() ?? 0.5,
      rightEyeOpen: (response['right_eye_open'] as num?)?.toDouble() ?? 0.5,
      poseReliable: response['pose_reliable'] as bool? ?? false,
      message:
          response['message'] as String? ??
          (faceCount == 1
              ? 'Desktop face signal locked.'
              : 'No face detected.'),
    );
  }

  static Future<File?> extractFace(String imagePath) async {
    if (!await available) return null;
    try {
      final response = await _post('/face-crop', {'image_path': imagePath});
      final cropPath = response['image_path'] as String?;
      if (cropPath == null || cropPath.isEmpty) return null;
      final crop = File(cropPath);
      return crop.existsSync() ? crop : null;
    } catch (_) {
      return null;
    }
  }

  static Future<BackendMatch?> verify({
    required String referenceImagePath,
    required String liveImagePath,
    String? referenceEmbedding,
  }) async {
    if (!await available) return null;
    final response = await _post('/verify', {
      'reference_image_path': referenceImagePath,
      'live_image_path': liveImagePath,
      'reference_embedding': referenceEmbedding,
      'backend_preference': 'auto',
    });
    return BackendMatch(
      isMatch: response['is_match'] as bool,
      score: (response['score'] as num).toDouble(),
      backend: response['backend'] as String,
      message: response['message'] as String,
      studentId: response['student_id'] as int?,
    );
  }

  static Future<BackendMatch?> identify({
    required String liveImagePath,
    required List<StudentRecord> candidates,
  }) async {
    if (!await available) return null;
    final embeddedCandidates = [
      for (final student in candidates)
        if (student.backendEmbedding != null)
          {
            'id': student.id ?? student.studentNumber.hashCode,
            'student_number': student.studentNumber,
            'full_name': student.fullName,
            'face_embedding': student.backendEmbedding,
          },
    ];
    if (embeddedCandidates.isEmpty) return null;
    final response = await _post('/identify', {
      'live_image_path': liveImagePath,
      'candidates': embeddedCandidates,
    });
    return BackendMatch(
      isMatch: response['is_match'] as bool,
      score: (response['score'] as num).toDouble(),
      backend: response['backend'] as String,
      message: response['message'] as String,
      studentId: response['student_id'] as int?,
    );
  }

  static Future<void> _start() async {
    if (_process != null) return;
    final root = _findProjectRoot();
    if (root == null) return;
    final python = File(
      '${root.path}${Platform.pathSeparator}.venv${Platform.pathSeparator}Scripts${Platform.pathSeparator}python.exe',
    );
    final api = File(
      '${root.path}${Platform.pathSeparator}App${Platform.pathSeparator}backend_api.py',
    );
    if (!python.existsSync() || !api.existsSync()) return;
    _process = await Process.start(python.path, [
      api.path,
      '--port',
      '$_port',
    ], workingDirectory: root.path);
    _process!.stdout.listen((_) {});
    _process!.stderr.listen((_) {});
  }

  static Directory? _findProjectRoot() {
    final starts = <Directory>[
      Directory.current,
      File(Platform.resolvedExecutable).parent,
    ];
    for (final start in starts) {
      var current = start;
      for (var depth = 0; depth < 8; depth++) {
        final api = File(
          '${current.path}${Platform.pathSeparator}App${Platform.pathSeparator}backend_api.py',
        );
        final python = File(
          '${current.path}${Platform.pathSeparator}.venv${Platform.pathSeparator}Scripts${Platform.pathSeparator}python.exe',
        );
        if (api.existsSync() && python.existsSync()) return current;
        final parent = current.parent;
        if (parent.path == current.path) break;
        current = parent;
      }
    }
    return null;
  }

  static Future<bool> _health() async {
    try {
      final client = HttpClient();
      client.connectionTimeout = const Duration(milliseconds: 700);
      final request = await client.getUrl(
        Uri.parse('http://127.0.0.1:$_port/health'),
      );
      final response = await request.close();
      await response.drain<void>();
      client.close();
      return response.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  static Future<Map<String, dynamic>> _post(
    String path,
    Map<String, Object?> body,
  ) async {
    final client = HttpClient();
    client.connectionTimeout = const Duration(seconds: 3);
    final request = await client.postUrl(
      Uri.parse('http://127.0.0.1:$_port$path'),
    );
    request.headers.contentType = ContentType.json;
    request.write(jsonEncode(body));
    final response = await request.close();
    final responseBody = await utf8.decodeStream(response);
    client.close();
    final decoded = jsonDecode(responseBody) as Map<String, dynamic>;
    if (response.statusCode >= 400 || decoded['ok'] != true) {
      throw FaceEngineException(decoded['error']?.toString() ?? responseBody);
    }
    return decoded;
  }
}

class BackendEmbedding {
  const BackendEmbedding({required this.embedding, required this.backend});

  final String embedding;
  final String backend;

  List<double> get signature {
    final decoded = jsonDecode(embedding);
    if (decoded is! List || decoded.isEmpty) {
      throw FaceEngineException(
        'The desktop FaceNet service returned an invalid embedding.',
      );
    }
    return decoded.map((value) => (value as num).toDouble()).toList();
  }
}

class BackendMatch {
  const BackendMatch({
    required this.isMatch,
    required this.score,
    required this.backend,
    required this.message,
    this.studentId,
  });

  final bool isMatch;
  final double score;
  final String backend;
  final String message;
  final int? studentId;
}

class AppColors {
  static const background = Color(0xFF050B18);
  static const sidebar = Color(0xFF020814);
  static const panel = Color(0xCC0D1C36);
  static const panelWeak = Color(0x99101D33);
  static const border = Color(0x267DD3FC);
  static const activeNav = Color(0x2422D3EE);
  static const cyanSoft = Color(0x6622D3EE);
  static const cyan = Color(0xFF22D3EE);
  static const sky = Color(0xFF38BDF8);
  static const blue = Color(0xFF3B82F6);
  static const green = Color(0xFF4ADE80);
  static const amber = Color(0xFFFBBF24);
  static const red = Color(0xFFFB7185);
  static const muted = Color(0xFF8FA9C2);
  static const soft = Color(0xFFC9DCED);
}
