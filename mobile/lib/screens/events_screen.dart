import 'package:flutter/material.dart';

import '../core/state.dart';

/// World-famous events (placeholder until the Events screen is built).
class EventsScreen extends StatelessWidget {
  const EventsScreen({super.key, required this.state});
  final AppState state;

  @override
  Widget build(BuildContext context) => const Scaffold(backgroundColor: Colors.transparent, body: SizedBox());
}
