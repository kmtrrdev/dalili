import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'shell.dart';

/// The Dalili website - the one UI, on the web and in the app - inside a native shell (shell.dart). The server comes
/// from the build: --dart-define=DALILI_SERVER=https://...
const server = String.fromEnvironment('DALILI_SERVER',
    defaultValue: 'https://dalili.gentlecliff-bcd5cc42.eastus.azurecontainerapps.io');

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent, systemNavigationBarColor: Color(0xFF04060C)));
  runApp(const DaliliApp());
}

class DaliliApp extends StatelessWidget {
  const DaliliApp({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Dalili',
        debugShowCheckedModeBanner: false,
        theme: ThemeData(brightness: Brightness.dark, scaffoldBackgroundColor: const Color(0xFF04060C),
            colorSchemeSeed: const Color(0xFF3DE0D0), useMaterial3: true),
        home: Shell(server: Uri.parse(server)),
      );
}
