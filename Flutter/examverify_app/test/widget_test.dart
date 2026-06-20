import 'package:examverify_app/main.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets('ExamVerify login renders production shell', (
    WidgetTester tester,
  ) async {
    await tester.pumpWidget(MaterialApp(home: LoginPage(onLogin: (_) {})));
    await tester.pump(const Duration(milliseconds: 300));

    expect(find.text('Sign in'), findsWidgets);
    expect(find.text('Sign in as Admin'), findsOneWidget);
    expect(find.text('Sign in as Invigilator'), findsOneWidget);
    expect(find.text('Request Admin Access'), findsOneWidget);
    expect(find.text('Identity Gateway'), findsNothing);
    expect(find.text('Access Secure Console'), findsNothing);
    expect(find.text('Backend URL'), findsNothing);
    expect(find.textContaining('Demo accounts'), findsNothing);
  });

  testWidgets('ExamVerify dashboard renders', (WidgetTester tester) async {
    await tester.pumpWidget(
      const ExamVerifyApp(skipPersistence: true, skipAuth: true),
    );
    await tester.pump(const Duration(seconds: 2));

    expect(find.text('Operations Dashboard'), findsOneWidget);
    expect(find.text('REGISTERED STUDENTS'), findsOneWidget);
  });

  testWidgets('exam session selector tolerates duplicate and refreshed rows', (
    WidgetTester tester,
  ) async {
    const sessionA = ExamSessionRecord(
      id: 1,
      courseCode: 'DIT410',
      courseName: 'Management Information Systems',
      program: 'DIT',
      level: '4',
      examDate: '2026-06-18',
      startTime: '09:00',
      endTime: '12:00',
      venue: 'Room 116',
      status: 'active',
    );
    const duplicateSessionA = ExamSessionRecord(
      id: 1,
      courseCode: 'DIT410',
      courseName: 'Management Information Systems',
      program: 'DIT',
      level: '4',
      examDate: '2026-06-18',
      startTime: '09:00',
      endTime: '12:00',
      venue: 'Room 116',
      status: 'active',
    );
    const sessionB = ExamSessionRecord(
      id: 2,
      courseCode: 'DIT420',
      courseName: 'Network Security',
      program: 'DIT',
      level: '4',
      examDate: '2026-06-19',
      startTime: '09:00',
      endTime: '12:00',
      venue: 'Room 210',
      status: 'active',
    );

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ExamSessionSelector(
            sessions: const [sessionA, duplicateSessionA],
            selectedId: sessionA.id,
            onChanged: (_) {},
          ),
        ),
      ),
    );
    expect(tester.takeException(), isNull);
    expect(find.text(sessionA.label), findsOneWidget);

    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ExamSessionSelector(
            sessions: const [sessionB],
            selectedId: sessionB.id,
            onChanged: (_) {},
          ),
        ),
      ),
    );
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(find.text(sessionB.label), findsOneWidget);
  });
}
