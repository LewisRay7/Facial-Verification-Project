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
}
