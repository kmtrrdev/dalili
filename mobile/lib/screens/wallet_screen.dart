import 'dart:math' as math;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';
import 'trip_helpers.dart';

const _filters = ['all', 'upcoming', 'past', 'drafts'];

/// My trips: every saved trip as a pass in a wallet. The passes lie stacked with only their tops showing; tap one
/// and it slides out of the stack (the others make room), tap it again - or Open - to load the trip. Long-press a
/// pass to delete it.
class WalletScreen extends StatefulWidget {
  const WalletScreen({super.key, required this.state});
  final AppState state;

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  String _filter = 'all';
  String? _open; // the pass out of the stack
  String? _loading;

  AppState get st => widget.state;

  @override
  void initState() {
    super.initState();
    st.addListener(_refresh);
    st.refreshHome();
  }

  @override
  void dispose() {
    st.removeListener(_refresh);
    super.dispose();
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  Future<void> _openTrip(Map<String, dynamic> t) async {
    final id = '${t['trip_id']}';
    if (_loading != null) return;
    setState(() => _loading = id);
    final ok = await st.openTrip(id);
    if (!mounted) return;
    setState(() => _loading = null);
    if (!ok) return toast(context, tr('errNet'));
    Navigator.of(context).pop();
    // A draft has no pass yet: its conversation is where it continues.
    st.goTab(st.plan != null ? Tabs.trip : Tabs.chat);
  }

  Future<void> _delete(Map<String, dynamic> t) async {
    HapticFeedback.mediumImpact();
    final yes = await showDialog<bool>(
          context: context,
          builder: (c) => AlertDialog(
            title: Text(tr('deleteQ')),
            content: Text(t['destination'] == null ? '' : '${t['destination']}'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(c, false), child: Text(tr('cancel'))),
              FilledButton(
                style: FilledButton.styleFrom(backgroundColor: DC.rose, foregroundColor: Colors.white, minimumSize: const Size(80, 44)),
                onPressed: () => Navigator.pop(c, true),
                child: Text(tr('delete')),
              ),
            ],
          ),
        ) ??
        false;
    if (!yes || !mounted) return;
    try {
      await st.deleteTrip('${t['trip_id']}');
      if (mounted) toast(context, tr('deleted'));
    } catch (_) {
      if (mounted) toast(context, tr('errNet'));
    }
  }

  void _planNew() {
    st.newTrip();
    Navigator.of(context).pop();
    st.goTab(Tabs.chat);
  }

  @override
  Widget build(BuildContext context) {
    final today = DateTime.now().toIso8601String().substring(0, 10);
    final list = filterTrips(st.trips, _filter, today);
    if (_open != null && !list.any((t) => t['trip_id'] == _open)) _open = null;
    return Scaffold(
      backgroundColor: Colors.transparent,
      body: SkyBackground(
        child: SafeArea(
          bottom: false,
          child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Padding(
              padding: const EdgeInsetsDirectional.fromSTEB(4, 4, 16, 0),
              child: Row(children: [
                const BackButton(),
                const SizedBox(width: 4),
                Expanded(
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    Text(L('WALLET', 'المحفظة'), style: mono(size: 10.5, spacing: 2, color: context.faint, weight: FontWeight.w800)),
                    Text(tr('tripsTitle'), style: display(size: 26, color: context.ink)),
                  ]),
                ),
                if (st.trips.isNotEmpty) Pill('${st.trips.length}', color: DC.teal, icon: Icons.confirmation_number_rounded),
              ]),
            ),
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 6),
              child: Row(children: [
                for (final f in _filters)
                  Padding(
                    padding: const EdgeInsetsDirectional.only(end: 8),
                    child: _FilterPill(
                      label: tr(f),
                      count: filterTrips(st.trips, f, today).length,
                      on: f == _filter,
                      onTap: () => setState(() {
                        _filter = f;
                        _open = null;
                      }),
                    ),
                  ),
              ]),
            ),
            Expanded(
              child: RefreshIndicator(
                onRefresh: st.refreshHome,
                child: list.isEmpty
                    ? ListView(
                        physics: const AlwaysScrollableScrollPhysics(),
                        children: [_EmptyWallet(any: st.trips.isNotEmpty, onPlan: _planNew)],
                      )
                    : SingleChildScrollView(
                        physics: const AlwaysScrollableScrollPhysics(parent: BouncingScrollPhysics()),
                        padding: EdgeInsets.fromLTRB(16, 12, 16, MediaQuery.viewPaddingOf(context).bottom + 32),
                        child: _Stack(
                          key: ValueKey(_filter),
                          trips: list,
                          open: _open,
                          loading: _loading,
                          today: today,
                          onTap: (t) {
                            if (_open == t['trip_id']) {
                              _openTrip(t);
                              return;
                            }
                            HapticFeedback.selectionClick();
                            setState(() => _open = '${t['trip_id']}');
                          },
                          onClose: () => setState(() => _open = null),
                          onOpen: _openTrip,
                          onDelete: _delete,
                        ),
                      ),
              ),
            ),
          ]),
        ),
      ),
    );
  }
}

class _FilterPill extends StatelessWidget {
  const _FilterPill({required this.label, required this.count, required this.on, required this.onTap});
  final String label;
  final int count;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: AnimatedContainer(
          duration: const Duration(milliseconds: 220),
          constraints: const BoxConstraints(minHeight: 44),
          padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
          decoration: BoxDecoration(
            gradient: on ? DC.brand : null,
            color: on ? null : context.card.withValues(alpha: .85),
            borderRadius: BorderRadius.circular(999),
            border: Border.all(color: on ? Colors.transparent : context.line),
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            Text(label, style: TextStyle(fontWeight: FontWeight.w800, fontSize: 13, color: on ? DC.onBrand : context.ink)),
            const SizedBox(width: 6),
            Text('$count', style: mono(size: 12, color: on ? DC.onBrand : context.faint)),
          ]),
        ),
      );
}

/// The passes, overlapping like cards in a wallet: each shows its top band; the open one comes out whole and the
/// ones after it move below it.
class _Stack extends StatelessWidget {
  const _Stack({
    super.key,
    required this.trips,
    required this.open,
    required this.loading,
    required this.today,
    required this.onTap,
    required this.onClose,
    required this.onOpen,
    required this.onDelete,
  });
  final List<Map<String, dynamic>> trips;
  final String? open, loading;
  final String today;
  final ValueChanged<Map<String, dynamic>> onTap, onOpen, onDelete;
  final VoidCallback onClose;

  @override
  Widget build(BuildContext context) {
    final ts = (MediaQuery.textScalerOf(context).scale(16) / 16).clamp(1.0, 1.6);
    final cardH = 248 * ts;
    final peek = 82 * ts;
    final e = trips.indexWhere((t) => t['trip_id'] == open);
    double top(int i) => e < 0 || i <= e ? i * peek : e * peek + cardH + 16 + (i - e - 1) * peek;
    final height = top(trips.length - 1) + cardH;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 420),
      curve: Curves.easeOutCubic,
      height: height,
      child: Stack(clipBehavior: Clip.none, children: [
        for (var i = 0; i < trips.length; i++)
          AnimatedPositioned(
            key: ValueKey(trips[i]['trip_id']),
            duration: const Duration(milliseconds: 420),
            curve: Curves.easeOutCubic,
            top: top(i),
            left: 0,
            right: 0,
            height: cardH,
            child: Reveal(
              delay: Duration(milliseconds: 70 * math.min(i, 8)),
              child: _TiltIn(
                flat: i == e,
                child: _WalletPass(
                  t: trips[i],
                  height: cardH,
                  open: i == e,
                  loading: loading == trips[i]['trip_id'],
                  past: '${trips[i]['end_date'] ?? '9'}'.compareTo(today) < 0 && trips[i]['status'] == 'planned',
                  onTap: () => onTap(trips[i]),
                  onClose: onClose,
                  onOpen: () => onOpen(trips[i]),
                  onDelete: () => onDelete(trips[i]),
                ),
              ),
            ),
          ),
      ]),
    );
  }
}

/// Passes in the stack lean back a little (depth); the open one comes up flat and can be tilted with a finger.
class _TiltIn extends StatelessWidget {
  const _TiltIn({required this.flat, required this.child});
  final bool flat;
  final Widget child;

  @override
  Widget build(BuildContext context) => TweenAnimationBuilder<double>(
        tween: Tween(end: flat ? 0 : 1),
        duration: const Duration(milliseconds: 420),
        curve: Curves.easeOutCubic,
        builder: (context, v, child) => Transform(
          alignment: Alignment.topCenter,
          transform: perspective()..rotateX(-.16 * v),
          child: child,
        ),
        child: flat ? Tilt3D(maxAngle: .1, child: child) : child,
      );
}

class _WalletPass extends StatelessWidget {
  const _WalletPass({
    required this.t,
    required this.height,
    required this.open,
    required this.loading,
    required this.past,
    required this.onTap,
    required this.onClose,
    required this.onOpen,
    required this.onDelete,
  });
  final Map<String, dynamic> t;
  final double height;
  final bool open, loading, past;
  final VoidCallback onTap, onClose, onOpen, onDelete;

  @override
  Widget build(BuildContext context) {
    final cities = (t['cities'] as List? ?? const []).map((e) => '$e').toList();
    final status = '${t['status'] ?? 'collecting'}';
    final planned = status == 'planned';
    final mode = '${t['mode'] ?? 'balanced'}';
    final accent = planned ? (DC.mode[mode] ?? DC.teal) : ({'needs_input': DC.amber, 'error': DC.rose}[status] ?? DC.violet);
    final cur = t['currency'] as String?;
    final days = t['days'];
    final pax = t['travelers'];
    final origin = '${t['origin'] ?? ''}';
    final dest = cities.isEmpty ? '…' : cities.first;
    final stubH = 70 * (height / 248);
    return Pressable(
      scale: .98,
      onTap: onTap,
      onLongPress: onDelete,
      child: Ticket(
        elevation: open ? 14 : 8,
        gradient: LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color.lerp(context.ticket, accent, context.dark ? .26 : .18)!, context.ticket],
        ),
        main: SizedBox(
          height: height - stubH - 22,
          child: Stack(children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 14, 18, 8),
              child: LayoutBuilder(
                builder: (context, c) => FittedBox(
                  fit: BoxFit.scaleDown,
                  alignment: AlignmentDirectional.topStart,
                  child: SizedBox(
                    width: c.maxWidth,
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                      // The band that shows while the pass sits in the stack.
                      Row(children: [
                        Expanded(
                          child: Text(cities.isEmpty ? '…' : routeText(cities), maxLines: 1, overflow: TextOverflow.ellipsis,
                              style: display(size: 20, color: context.ink)),
                        ),
                        const SizedBox(width: 8),
                        Pill(tr('st.$status'), color: accent),
                      ]),
                      const SizedBox(height: 2),
                      Text(
                        t['start_date'] == null
                            ? L('Dates not set yet', 'لسه من غير تواريخ')
                            : '${fmtDate(t['start_date'] as String?)} – ${fmtDate(t['end_date'] as String?, year: true)}',
                        style: mono(size: 12, color: context.muted, weight: FontWeight.w600),
                      ),
                      const SizedBox(height: 14),
                      Row(children: [
                        Flexible(child: _end(context, origin.isEmpty ? '—' : origin, false)),
                        Expanded(
                          child: Padding(
                            padding: const EdgeInsets.symmetric(horizontal: 8),
                            child: RouteArc(progress: past ? 1 : (planned ? .55 : .15), color: accent, height: 34),
                          ),
                        ),
                        Flexible(child: _end(context, dest, true)),
                      ]),
                      const SizedBox(height: 12),
                      Row(children: [
                        Expanded(child: PassField(L('Days', 'أيام'), days == null ? '—' : '$days')),
                        Expanded(child: PassField(L('Pax', 'مسافرين'), pax == null ? '—' : '$pax')),
                        Expanded(child: PassField(tr('total'), t['total'] == null ? '—' : money(t['total'] as num?, cur))),
                        Expanded(
                          child: PassField(tr('tripScore'), t['score'] == null ? '—' : '${t['score']}', end: true, valueColor: accent),
                        ),
                      ]),
                    ]),
                  ),
                ),
              ),
            ),
            if (past)
              PositionedDirectional(
                end: 14,
                bottom: 2,
                // Faded by colour, not Opacity: a layer inside a Ticket breaks its painting (see the report).
                child: IgnorePointer(
                  child: Stamp(
                      label: L('travelled ✦ travelled', 'اتسافرت ✦ اتسافرت'), center: '✈', color: accent.withValues(alpha: .75), size: 66),
                ),
              ),
          ]),
        ),
        stub: SizedBox(
          height: stubH,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 14),
            child: Row(children: [
              Expanded(child: Barcode('${t['trip_id']}', height: 30)),
              const SizedBox(width: 8),
              if (open) ...[
                IconButton(
                  tooltip: tr('delete'),
                  onPressed: onDelete,
                  icon: const Icon(Icons.delete_outline_rounded, color: DC.rose),
                ),
                IconButton(
                  tooltip: MaterialLocalizations.of(context).closeButtonTooltip,
                  onPressed: onClose,
                  icon: Icon(Icons.unfold_less_rounded, color: context.muted),
                ),
                FilledButton(
                  style: FilledButton.styleFrom(minimumSize: const Size(64, 44), padding: const EdgeInsets.symmetric(horizontal: 14)),
                  onPressed: loading ? null : onOpen,
                  child: loading
                      ? const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2))
                      : Text(L('Open', 'افتح')),
                ),
              ],
            ]),
          ),
        ),
      ),
    );
  }

  Widget _end(BuildContext context, String city, bool atEnd) => Text(
        city,
        maxLines: 1,
        overflow: TextOverflow.ellipsis,
        textAlign: atEnd ? TextAlign.end : TextAlign.start,
        style: display(size: 15, color: context.ink, weight: FontWeight.w800),
      );
}

class _EmptyWallet extends StatelessWidget {
  const _EmptyWallet({required this.any, required this.onPlan});
  final bool any; // there are trips, just none under this filter
  final VoidCallback onPlan;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(32, 40, 32, 32),
        child: Column(children: [
          Float(
            child: SizedBox(
              width: 220,
              child: Opacity(
                opacity: .85,
                child: Ticket(
                  main: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 16, 16, 12),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                      Text('DALILI', style: mono(size: 11, spacing: 3, color: DC.teal)),
                      const SizedBox(height: 8),
                      RouteArc(progress: .3, color: context.faint, height: 34),
                    ]),
                  ),
                  stub: Padding(
                    padding: const EdgeInsets.fromLTRB(16, 8, 16, 14),
                    child: Barcode('wallet', height: 26, color: context.faint.withValues(alpha: .5)),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(height: 26),
          Text(any ? L('Nothing here', 'مفيش حاجة هنا') : tr('noTrips'),
              textAlign: TextAlign.center, style: display(size: 22, color: context.ink)),
          const SizedBox(height: 6),
          Text(any ? L('No trips under this filter.', 'مفيش رحلات تحت الفلتر ده.') : tr('noTripsSub'),
              textAlign: TextAlign.center, style: TextStyle(color: context.muted)),
          const SizedBox(height: 22),
          ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 280),
            child: BrandButton(label: tr('planNew'), icon: Icons.add_rounded, onTap: onPlan),
          ),
        ]),
      );
}
