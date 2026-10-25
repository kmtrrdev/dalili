import 'package:flutter/material.dart';

import '../core/state.dart';

/// The landmark camera (placeholder until the screen is built).
class LandmarkScreen extends StatelessWidget {
  const LandmarkScreen({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) => const Scaffold(body: SizedBox());
}
