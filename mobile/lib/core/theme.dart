import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

/// Dalili's colours (the same as the website).
class DC {
  static const teal = Color(0xFF3DE0D0);
  static const tealDeep = Color(0xFF0B9E90);
  static const sky = Color(0xFF36B7FF);
  static const violet = Color(0xFF9B8CFF);
  static const amber = Color(0xFFFFB454);
  static const rose = Color(0xFFFF6B8B);
  static const green = Color(0xFF5EE38F);
  static const night = Color(0xFF04060C);
  static const nightCard = Color(0xFF0C1322);
  static const nightCard2 = Color(0xFF121B2E);
  static const day = Color(0xFFEEF3FB);

  static const brand = LinearGradient(colors: [teal, sky], begin: Alignment.topLeft, end: Alignment.bottomRight);
  static const aurora = LinearGradient(
      colors: [Color(0xFF0E3B4A), Color(0xFF1B1F4B), Color(0xFF3A2352)], begin: Alignment.topLeft, end: Alignment.bottomRight);

  static const tag = {
    'beach': Color(0xFF2BB3D6), 'culture': Color(0xFF9B8CFF), 'history': Color(0xFFD99A3E), 'nature': Color(0xFF44C267),
    'ski': Color(0xFF6FA8DC), 'food': Color(0xFFFF8A5C), 'nightlife': Color(0xFFD25BD8), 'shopping': Color(0xFFFF6B8B),
    'relax': Color(0xFF3DE0D0), 'adventure': Color(0xFFE0B030),
  };
  static const emoji = {
    'beach': '🏖️', 'culture': '🏛️', 'history': '🏺', 'nature': '🌿', 'ski': '⛷️', 'food': '🍽️', 'nightlife': '🌙',
    'shopping': '🛍️', 'relax': '🧖', 'adventure': '🧗',
  };
}

ThemeData buildTheme(Brightness b, String lang) {
  final dark = b == Brightness.dark;
  final scheme = ColorScheme.fromSeed(
    seedColor: DC.teal,
    brightness: b,
    primary: dark ? DC.teal : DC.tealDeep,
    secondary: DC.violet,
    surface: dark ? DC.nightCard : Colors.white,
    error: DC.rose,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, brightness: b);
  final body = lang == 'ar' ? GoogleFonts.cairoTextTheme(base.textTheme) : GoogleFonts.interTextTheme(base.textTheme);
  final display = lang == 'ar' ? GoogleFonts.cairo : GoogleFonts.spaceGrotesk;
  final ink = dark ? const Color(0xFFEAF1FF) : const Color(0xFF0E1A2F);
  final text = body
      .apply(bodyColor: ink, displayColor: ink)
      .copyWith(
        headlineLarge: display(fontSize: 32, fontWeight: FontWeight.w700, color: ink, height: 1.1),
        headlineMedium: display(fontSize: 26, fontWeight: FontWeight.w700, color: ink, height: 1.15),
        titleLarge: display(fontSize: 20, fontWeight: FontWeight.w700, color: ink),
        titleMedium: display(fontSize: 16, fontWeight: FontWeight.w700, color: ink),
      );
  return base.copyWith(
    scaffoldBackgroundColor: dark ? DC.night : DC.day,
    textTheme: text,
    appBarTheme: AppBarTheme(
      backgroundColor: Colors.transparent, elevation: 0, scrolledUnderElevation: 0, centerTitle: false,
      foregroundColor: ink, titleTextStyle: display(fontSize: 20, fontWeight: FontWeight.w700, color: ink)),
    cardTheme: CardThemeData(
      color: dark ? DC.nightCard : Colors.white, elevation: 0, margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20),
          side: BorderSide(color: dark ? Colors.white.withValues(alpha: .07) : const Color(0x1A1C3460)))),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: dark ? const Color(0xF20A1020) : Colors.white,
      indicatorColor: DC.teal.withValues(alpha: dark ? .18 : .22),
      labelTextStyle: WidgetStatePropertyAll(body.labelMedium?.copyWith(fontWeight: FontWeight.w600)),
      height: 68,
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark ? const Color(0xFF0A1120) : const Color(0xFFF6F9FE),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16),
          borderSide: BorderSide(color: dark ? Colors.white.withValues(alpha: .10) : const Color(0x261C3460))),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: scheme.primary, width: 1.6)),
      errorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: const BorderSide(color: DC.rose)),
      focusedErrorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: const BorderSide(color: DC.rose, width: 1.6)),
    ),
    chipTheme: ChipThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      side: BorderSide(color: dark ? Colors.white.withValues(alpha: .12) : const Color(0x261C3460)),
      backgroundColor: dark ? DC.nightCard2 : Colors.white,
      selectedColor: DC.teal.withValues(alpha: .22),
      labelStyle: body.labelLarge?.copyWith(fontWeight: FontWeight.w600, color: ink),
    ),
    filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(
      backgroundColor: dark ? DC.teal : DC.tealDeep, foregroundColor: dark ? const Color(0xFF04110F) : Colors.white,
      minimumSize: const Size(48, 52), shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      textStyle: body.titleSmall?.copyWith(fontWeight: FontWeight.w700))),
    outlinedButtonTheme: OutlinedButtonThemeData(style: OutlinedButton.styleFrom(
      minimumSize: const Size(48, 48), foregroundColor: ink,
      side: BorderSide(color: dark ? Colors.white.withValues(alpha: .16) : const Color(0x331C3460)),
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)))),
    snackBarTheme: SnackBarThemeData(behavior: SnackBarBehavior.floating,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14))),
    dividerColor: dark ? Colors.white.withValues(alpha: .07) : const Color(0x141C3460),
  );
}

extension Muted on BuildContext {
  bool get dark => Theme.of(this).brightness == Brightness.dark;
  Color get muted => dark ? const Color(0xFF93A3C2) : const Color(0xFF4F5F7B);
  Color get faint => dark ? const Color(0xFF5F6F8F) : const Color(0xFF7C89A1);
  Color get card => dark ? DC.nightCard : Colors.white;
  Color get card2 => dark ? DC.nightCard2 : const Color(0xFFF3F6FC);
  Color get line => dark ? Colors.white.withValues(alpha: .08) : const Color(0x1A1C3460);
}
