import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

import 'i18n.dart';

/// Dalili's colours. The app is a travel wallet: boarding passes on a night sky (dark) or cream paper on a pale
/// morning sky (light), with the website's teal as the brand and amber for "gate" highlights.
class DC {
  static const teal = Color(0xFF3DE0D0);
  static const tealDeep = Color(0xFF0B9E90);
  static const sky = Color(0xFF36B7FF);
  static const violet = Color(0xFF9B8CFF);
  static const amber = Color(0xFFFFB454);
  static const rose = Color(0xFFFF6B8B);
  static const green = Color(0xFF5EE38F);
  static const coral = Color(0xFFFF8A5C);
  static const night = Color(0xFF060912);
  static const nightCard = Color(0xFF0F1626);
  static const nightCard2 = Color(0xFF16203A);
  static const day = Color(0xFFE9EEF7);
  static const paper = Color(0xFFFFFCF5);
  static const onBrand = Color(0xFF04110F);

  static const brand = LinearGradient(colors: [teal, sky], begin: Alignment.topLeft, end: Alignment.bottomRight);
  static const sunset = LinearGradient(colors: [amber, coral], begin: Alignment.topLeft, end: Alignment.bottomRight);
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

  /// The plan modes' colours (ticket accents) - the same order everywhere.
  static const mode = {'balanced': teal, 'budget': green, 'comfort': violet, 'experience': amber};
}

/// Monospace for the codes on a pass (IATA codes, times, seat-like labels) - Latin digits in both languages.
TextStyle mono({double size = 14, FontWeight weight = FontWeight.w700, Color? color, double? spacing, double? height}) =>
    GoogleFonts.jetBrainsMono(fontSize: size, fontWeight: weight, color: color, letterSpacing: spacing, height: height);

/// The display face: Space Grotesk, or Cairo for Arabic.
TextStyle display({double size = 20, FontWeight weight = FontWeight.w700, Color? color, double? height, double? spacing}) =>
    (isArabic ? GoogleFonts.cairo : GoogleFonts.spaceGrotesk)(
        fontSize: size, fontWeight: weight, color: color, height: height, letterSpacing: spacing);

ThemeData buildTheme(Brightness b, String lang) {
  final dark = b == Brightness.dark;
  final scheme = ColorScheme.fromSeed(
    seedColor: DC.teal,
    brightness: b,
    primary: dark ? DC.teal : DC.tealDeep,
    secondary: DC.violet,
    surface: dark ? DC.nightCard : DC.paper,
    error: DC.rose,
  );
  final base = ThemeData(useMaterial3: true, colorScheme: scheme, brightness: b);
  final body = lang == 'ar' ? GoogleFonts.cairoTextTheme(base.textTheme) : GoogleFonts.interTextTheme(base.textTheme);
  final face = lang == 'ar' ? GoogleFonts.cairo : GoogleFonts.spaceGrotesk;
  final ink = dark ? const Color(0xFFEAF1FF) : const Color(0xFF0E1A2F);
  final text = body.apply(bodyColor: ink, displayColor: ink).copyWith(
        headlineLarge: face(fontSize: 34, fontWeight: FontWeight.w700, color: ink, height: 1.05),
        headlineMedium: face(fontSize: 26, fontWeight: FontWeight.w700, color: ink, height: 1.12),
        titleLarge: face(fontSize: 20, fontWeight: FontWeight.w700, color: ink),
        titleMedium: face(fontSize: 16, fontWeight: FontWeight.w700, color: ink),
      );
  final line = dark ? Colors.white.withValues(alpha: .10) : const Color(0x261C3460);
  return base.copyWith(
    scaffoldBackgroundColor: dark ? DC.night : DC.day,
    textTheme: text,
    splashFactory: InkSparkle.splashFactory,
    appBarTheme: AppBarTheme(
        backgroundColor: Colors.transparent, elevation: 0, scrolledUnderElevation: 0, centerTitle: false,
        foregroundColor: ink, titleTextStyle: face(fontSize: 20, fontWeight: FontWeight.w700, color: ink)),
    cardTheme: CardThemeData(
        color: dark ? DC.nightCard : DC.paper, elevation: 0, margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22), side: BorderSide(color: line))),
    bottomSheetTheme: BottomSheetThemeData(
        backgroundColor: dark ? DC.nightCard : DC.paper, showDragHandle: true,
        shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(28)))),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: dark ? const Color(0xFF0B1222) : Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide.none),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: line)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: BorderSide(color: scheme.primary, width: 1.6)),
      errorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: const BorderSide(color: DC.rose)),
      focusedErrorBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(16), borderSide: const BorderSide(color: DC.rose, width: 1.6)),
    ),
    chipTheme: ChipThemeData(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(999)),
      side: BorderSide(color: line),
      backgroundColor: dark ? DC.nightCard2 : Colors.white,
      selectedColor: DC.teal.withValues(alpha: .22),
      labelStyle: body.labelLarge?.copyWith(fontWeight: FontWeight.w600, color: ink),
    ),
    filledButtonTheme: FilledButtonThemeData(style: FilledButton.styleFrom(
        backgroundColor: dark ? DC.teal : DC.tealDeep, foregroundColor: dark ? DC.onBrand : Colors.white,
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
  Color get ink => dark ? const Color(0xFFEAF1FF) : const Color(0xFF0E1A2F);
  Color get muted => dark ? const Color(0xFF93A3C2) : const Color(0xFF4F5F7B);
  Color get faint => dark ? const Color(0xFF5F6F8F) : const Color(0xFF7C89A1);
  Color get card => dark ? DC.nightCard : DC.paper;
  Color get card2 => dark ? DC.nightCard2 : const Color(0xFFF3EFE4);
  Color get line => dark ? Colors.white.withValues(alpha: .08) : const Color(0x1A1C3460);

  /// A pass's paper: dark glass at night, cream in the day.
  Color get ticket => dark ? const Color(0xFF111A2E) : DC.paper;
  Color get ticketEdge => dark ? Colors.white.withValues(alpha: .09) : const Color(0x22000000);

  /// Space for the floating dock at the bottom of every tab (its height + the phone's own bottom inset).
  double get dockSpace => 96 + MediaQuery.viewPaddingOf(this).bottom;
}
