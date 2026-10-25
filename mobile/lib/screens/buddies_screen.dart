import 'package:flutter/material.dart';

import '../core/state.dart';

/// Travel buddies (for one trip when tripId is set, else all the traveller's groups) (placeholder until the screen is built).
class BuddiesScreen extends StatelessWidget {
  const BuddiesScreen({super.key, required this.state, this.tripId});
  final AppState state;
  final String? tripId;

  @override
  Widget build(BuildContext context) => const Scaffold(body: SizedBox());
}
