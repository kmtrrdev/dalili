import 'dart:async';
import 'dart:math' as math;
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:intl/intl.dart' hide TextDirection;
import 'package:shared_preferences/shared_preferences.dart';

import '../core/i18n.dart';
import '../core/state.dart';
import '../core/theme.dart';
import '../ui/motion.dart';
import '../ui/sky.dart';
import '../ui/ticket.dart';
import '../widgets/common.dart';

// The Hajj & Umrah guide: the rituals step by step, the miqat, prayer times in Makkah and Madinah, a checklist - and a
// short form that hands an Umrah to the planner. The guidance is fixed text (never written by the model), the same
// as the website's (frontend/js/pilgrimage.js), drawn from the widely followed practice published by the Saudi
// Ministry of Hajj and Umrah; it points to a scholar for rulings. Keep it word for word in step with the website.

const _nusuk = 'https://www.nusuk.sa';
const _ministry = 'https://www.haj.gov.sa';

// The holy cities' own palette, beside the app's: a deep green cover and a soft gold.
const _gold = Color(0xFFD9B66F);
const _goldDeep = Color(0xFF9C7425); // gold that still reads on cream paper
const _green = Color(0xFF14674F);
const _greenDeep = Color(0xFF062F26);
const _ivory = Color(0xFFF6EFDF);

Color _accent(BuildContext c) => c.dark ? _gold : _goldDeep;

// ---------------------------------------------------------------- the fixed guidance (as on the website)
// Each step: (title, text) in English and Arabic.
const _umrah = {
  'en': [
    ("1 · Ihram at the miqat", "Before the miqat: a full wash (ghusl) and perfume on the body (not the clothes). Men wear two white unstitched sheets and leave the head uncovered; women wear their usual modest clothes, without a face veil (niqab) or gloves. Make the intention for Umrah - \"Labbayka Allahumma 'umrah\" - and repeat the talbiyah (\"Labbayk Allahumma labbayk…\") until the tawaf begins. In ihram: no cutting hair or nails, no perfume, no hunting, no marital relations; men don't wear stitched clothes or cover the head."),
    ("2 · Tawaf", "Enter Masjid al-Haram with the right foot and the mosque's supplication. Men uncover the right shoulder during this tawaf. Start at the Black Stone corner: touch or kiss it if you can easily, otherwise point to it and say \"Bismillah, Allahu akbar\". Walk seven circuits with the Kaaba on your left (men walk briskly in the first three if possible). Between the Yemeni corner and the Black Stone: \"Rabbana atina fid-dunya hasanah wa fil-akhirati hasanah wa qina 'adhaban-nar\". Any supplication or dhikr in your own words is fine."),
    ("3 · Prayer behind Maqam Ibrahim · Zamzam", "Pray two rak'ahs behind Maqam Ibrahim if there is room - anywhere in the mosque if it's crowded - then drink Zamzam water."),
    ("4 · Sa'i between Safa and Marwah", "Go up Safa, recite \"Innas-Safa wal-Marwata min sha'a'irillah\", face the Kaaba and supplicate. Walk to Marwah (men hurry between the green lights) - that is one lap; back to Safa is the second. Seven laps, ending at Marwah, supplicating as you walk."),
    ("5 · Shaving or trimming", "Men shave the head (preferred) or trim it all over; women cut about a fingertip's length from the end of their hair. Your Umrah is complete and the restrictions of ihram are lifted."),
  ],
  'ar': [
    ("١ · الإحرام من الميقات", "قبل الميقات: الاغتسال والتطيّب في البدن (مش في ملابس الإحرام). الرجل يلبس إزار ورداء أبيضين غير مخيطين وراسه مكشوفة؛ والمرأة تلبس لبسها الساتر العادي من غير نقاب ولا قفازين. انوِ العمرة: «لبيك اللهم عمرة»، وكرّر التلبية («لبيك اللهم لبيك…») لحد ما تبدأ الطواف. في الإحرام: ممنوع قص الشعر والأظافر، والطيب، والصيد، والجماع؛ والرجل ما يلبسش مخيط وما يغطيش راسه."),
    ("٢ · الطواف", "ادخل المسجد الحرام برجلك اليمين وقول دعاء دخول المسجد. الرجل يكشف كتفه اليمين في الطواف ده (الاضطباع). ابدأ من ركن الحجر الأسود: استلمه أو قبّله لو سهل، وإلا شاور عليه وقول «بسم الله، الله أكبر». سبعة أشواط والكعبة على شمالك (والرجل يرمل في الأشواط التلاتة الأولى لو أمكن). بين الركن اليماني والحجر: «ربنا آتنا في الدنيا حسنة وفي الآخرة حسنة وقنا عذاب النار». ادعي واذكر بأي كلام من قلبك."),
    ("٣ · ركعتين خلف المقام · زمزم", "صلّي ركعتين خلف مقام إبراهيم لو في مكان - أو في أي حتة في المسجد لو زحمة - وبعدين اشرب من زمزم."),
    ("٤ · السعي بين الصفا والمروة", "اطلع الصفا واقرأ «إن الصفا والمروة من شعائر الله»، واستقبل الكعبة وادعي. امشي للمروة (والرجل يسرع بين العلمين الأخضرين) - ده شوط؛ والرجوع للصفا الشوط التاني. سبعة أشواط تخلص عند المروة، وادعي وانت ماشي."),
    ("٥ · الحلق أو التقصير", "الرجل يحلق شعره (وده الأفضل) أو يقصّره من كل الراس؛ والمرأة تقص قدر أنملة من أطراف شعرها. كده عمرتك تمت وتحللت من الإحرام."),
  ],
};

const _hajj = {
  'en': [
    ("The three ways", "Tamattu' (most pilgrims from abroad): an Umrah in the Hajj months, out of ihram, then ihram for Hajj on the 8th - a sacrifice is due. Qiran: Umrah and Hajj together in one ihram - a sacrifice is due. Ifrad: Hajj alone."),
    ("8 Dhu al-Hijjah · Tarwiyah", "Ihram for Hajj from where you are staying (for tamattu'), then to Mina: Dhuhr to Fajr prayed there, the four-rak'ah prayers shortened."),
    ("9 Dhu al-Hijjah · Arafah", "After sunrise, to Arafat - standing at Arafah is the heart of Hajj. Dhuhr and Asr combined and shortened, then supplication until sunset. After sunset, to Muzdalifah."),
    ("The night at Muzdalifah", "Maghrib and Isha combined; the night spent there; pebbles collected for the Jamarat."),
    ("10 Dhu al-Hijjah · the Day of Sacrifice (Eid)", "Stoning Jamarat al-Aqabah with seven pebbles, the sacrifice, shaving or trimming (the first release from ihram), and tawaf al-ifadah (with the sa'i for tamattu')."),
    ("11-13 Dhu al-Hijjah · the days of Tashreeq", "In Mina: after midday, stoning the three Jamarat - small, middle, then large - seven pebbles each. Leaving on the 12th before sunset is allowed."),
    ("Farewell tawaf", "The last act before leaving Makkah."),
    ("How to go", "Hajj is only through official channels: for Egyptians, the Ministry of Interior lottery, the Ministry of Social Solidarity or a licensed tourism company; for many other countries, the Nusuk Hajj platform. Dalili doesn't book Hajj."),
  ],
  'ar': [
    ("الأنساك التلاتة", "التمتع (أغلب الحجاج من برّه): عمرة في أشهر الحج، تتحلل، وبعدين تحرم بالحج يوم ٨ - وعليك هدي. القِران: عمرة وحج بإحرام واحد - وعليك هدي. الإفراد: حج بس."),
    ("٨ ذو الحجة · يوم التروية", "الإحرام بالحج من مكانك (للمتمتع)، وبعدين على منى: الظهر لحد الفجر هناك، والرباعية تتقصر."),
    ("٩ ذو الحجة · يوم عرفة", "بعد الشروق على عرفات - والوقوف بعرفة هو ركن الحج الأعظم. الظهر والعصر جمع وقصر، ودعاء لحد المغرب. وبعد الغروب على مزدلفة."),
    ("ليلة مزدلفة", "المغرب والعشاء جمع، والمبيت هناك، ولقط الحصى للجمرات."),
    ("١٠ ذو الحجة · يوم النحر (العيد)", "رمي جمرة العقبة بسبع حصيات، والهدي، والحلق أو التقصير (التحلل الأول)، وطواف الإفاضة (ومعاه السعي للمتمتع)."),
    ("١١-١٣ ذو الحجة · أيام التشريق", "في منى: بعد الزوال رمي الجمرات التلاتة - الصغرى فالوسطى فالكبرى - سبع حصيات لكل واحدة. ويجوز التعجّل يوم ١٢ قبل المغرب."),
    ("طواف الوداع", "آخر حاجة قبل ما تمشي من مكة."),
    ("إزاي تروح", "الحج من القنوات الرسمية بس: للمصريين قرعة وزارة الداخلية، أو وزارة التضامن الاجتماعي، أو شركة سياحة مرخّصة؛ ولدول كتير تانية منصة نسك حج. دليلي ما بيحجزش الحج."),
  ],
};

const _miqat = {
  'en': [
    ("Dhul Hulayfah (Abyar Ali)", "For pilgrims coming from Madinah - about 420 km from Makkah."),
    ("Al-Juhfah (near Rabigh)", "For Egypt, the Levant, North Africa and those coming from the west - about 186 km."),
    ("Qarn al-Manazil (As-Sayl al-Kabir)", "For Najd, Taif and the Gulf by road - about 75 km."),
    ("Yalamlam (As-Sa'diyyah)", "For Yemen and the south - about 100 km."),
    ("Dhat 'Irq", "For Iraq and the north-east - about 100 km."),
    ("Flying in", "Enter ihram before the plane passes the miqat on your route (the crew usually announce it): put the ihram clothes on before boarding or on board. Flying to Madinah first? Your miqat is then Dhul Hulayfah, on the way to Makkah."),
    ("Already in Makkah?", "For another Umrah, go out to the nearest point outside the sanctuary - usually Masjid Aisha at Tan'eem - and enter ihram there."),
  ],
  'ar': [
    ("ذو الحليفة (أبيار علي)", "للجاي من المدينة - حوالي ٤٢٠ كم من مكة."),
    ("الجحفة (قرب رابغ)", "لأهل مصر والشام والمغرب والجاي من الغرب - حوالي ١٨٦ كم."),
    ("قرن المنازل (السيل الكبير)", "لأهل نجد والطائف والخليج بالبر - حوالي ٧٥ كم."),
    ("يلملم (السعدية)", "لأهل اليمن والجنوب - حوالي ١٠٠ كم."),
    ("ذات عرق", "لأهل العراق والشمال الشرقي - حوالي ١٠٠ كم."),
    ("لو مسافر بالطيارة", "أحرم قبل ما الطيارة تعدّي الميقات اللي على طريقك (الطاقم عادة بيعلن): البس ملابس الإحرام قبل الطيارة أو جواها. لو نازل المدينة الأول، ميقاتك ذو الحليفة وانت رايح مكة."),
    ("لو انت في مكة أصلاً", "لعمرة تانية، اطلع لأقرب الحِل - عادة مسجد السيدة عائشة في التنعيم - وأحرم من هناك."),
  ],
};

// Where each of the five miqats lies from Makkah (degrees from north, km) - for the little compass map only.
const _miqatBearing = [(356.0, 420.0), (333.0, 186.0), (68.0, 75.0), (178.0, 100.0), (48.0, 100.0)];

const _check = {
  'en': [
    "A passport valid for at least six months, and a visa that allows Umrah (many nationalities can use the tourist e-visa).",
    "Book your Umrah and your visit to Ar-Rawdah in the Nusuk app.",
    "Check the latest health requirements (vaccinations such as meningitis) on the official Saudi sources before you travel.",
    "Men: two white ihram sheets and a belt. Everyone: unscented soap and toiletries for the days in ihram.",
    "Comfortable sandals, a small bag for your shoes in the mosque, a light prayer mat.",
    "Water bottle, unscented sunscreen, an umbrella for the sun, your usual medicines.",
    "Some Saudi riyals in cash for small expenses.",
    "Modest clothes; phone on silent in the mosques; patience in the crowds - never push at the Black Stone.",
  ],
  'ar': [
    "جواز سفر صالح ٦ شهور على الأقل، وتأشيرة تسمح بالعمرة (جنسيات كتير تقدر تستخدم التأشيرة السياحية الإلكترونية).",
    "احجز العمرة وزيارة الروضة من تطبيق نسك.",
    "اتأكد من آخر الاشتراطات الصحية (تطعيمات زي الحمى الشوكية) من المصادر السعودية الرسمية قبل السفر.",
    "للرجال: قطعتين إحرام بيض وحزام. للكل: صابون ومستلزمات من غير ريحة لأيام الإحرام.",
    "شبشب مريح، شنطة صغيرة للجزمة جوه المسجد، سجادة صلاة خفيفة.",
    "زجاجة مية، واقي شمس من غير ريحة، شمسية للشمس، أدويتك المعتادة.",
    "شوية ريال سعودي كاش للمصاريف الصغيرة.",
    "لبس محتشم، الموبايل صامت في المساجد، والصبر في الزحمة - وما تزقّش عند الحجر الأسود.",
  ],
};

const _prayerKeys = ['Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha'];
const _prayerNames = {
  'en': ['Fajr', 'Dhuhr', 'Asr', 'Maghrib', 'Isha'],
  'ar': ['الفجر', 'الظهر', 'العصر', 'المغرب', 'العشاء'],
};

String get _lang => isArabic ? 'ar' : 'en';
String _prayerName(String key) => _prayerNames[_lang]![_prayerKeys.indexOf(key)];

// ---------------------------------------------------------------- pure helpers (tested)
/// The time on the clocks of Makkah and Madinah (UTC+3 all year), as a DateTime whose UTC fields are that wall time.
DateTime makkahNow([DateTime? now]) => (now ?? DateTime.now()).toUtc().add(const Duration(hours: 3));

/// "2026-10-26" from a date's own fields.
String isoDay(DateTime d) =>
    '${d.year.toString().padLeft(4, '0')}-${d.month.toString().padLeft(2, '0')}-${d.day.toString().padLeft(2, '0')}';

/// One prayer on one day, at Makkah wall-clock time (UTC fields).
class PrayerSlot {
  const PrayerSlot(this.key, this.day, this.at);
  final String key; // Fajr..Isha
  final String day; // ISO date
  final DateTime at;
}

/// The first prayer after [now] (a [makkahNow] value) in the API's `days` ({iso: {times: {Fajr: "05:12", ...}}}),
/// or null when the days given are all behind it.
PrayerSlot? nextPrayer(Map<String, dynamic> days, DateTime now) {
  final keys = days.keys.toList()..sort();
  for (final iso in keys) {
    final d = DateTime.tryParse(iso);
    final times = (days[iso] as Map?)?['times'] as Map?;
    if (d == null || times == null) continue;
    for (final k in _prayerKeys) {
      final m = RegExp(r'(\d{1,2}):(\d{2})').firstMatch('${times[k] ?? ''}');
      if (m == null) continue;
      final at = DateTime.utc(d.year, d.month, d.day, int.parse(m[1]!), int.parse(m[2]!));
      if (at.isAfter(now)) return PrayerSlot(k, iso, at);
    }
  }
  return null;
}

/// The chat message that hands an Umrah to the planner - word for word the website's (pgMsg).
/// [date] is the departure already written out ("15 November 2026").
String umrahMessage({required bool arabic, required int nights, required int makkah, required String date,
    required int pax, String budget = '', required String from}) {
  final n = math.max(2, nights);
  final mk = math.min(n, math.max(1, makkah));
  final md = n - mk;
  final b = budget.trim(), f = from.trim();
  if (arabic) {
    return 'عايز أعمل عمرة: $n ليالي من $date ($mk في مكة${md > 0 ? ' و$md في المدينة' : ''}) لـ $pax '
        '${pax > 1 ? 'أفراد' : 'فرد'}${b.isNotEmpty ? '، الميزانية $b' : ''}، مسافر من $f';
  }
  return 'I want to do Umrah: $n nights from $date ($mk in Makkah${md > 0 ? ', $md in Madinah' : ''}) for $pax '
      'traveller${pax > 1 ? 's' : ''}${b.isNotEmpty ? ', budget $b' : ''}, flying from $f';
}

/// "02:14:09".
String countdownText(Duration d) {
  final s = d.isNegative ? 0 : d.inSeconds;
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(s ~/ 3600)}:${two(s % 3600 ~/ 60)}:${two(s % 60)}';
}

// A step title "1 · Ihram at the miqat" -> ("1", "Ihram at the miqat"); titles without a leading number stay whole.
(String?, String) _splitNumber(String title) {
  final m = RegExp(r'^([0-9٠-٩]+(?:-[0-9٠-٩]+)?)\s·\s(.+)$').firstMatch(title);
  return m == null ? (null, title) : (m[1], m[2]!);
}

String _cap(String s) => s.isEmpty ? s : s[0].toUpperCase() + s.substring(1);

DateTime? _parseDay(String? iso) => iso == null ? null : DateTime.tryParse(iso);

String _fmt(DateTime d, String pattern) => DateFormat(pattern, isArabic ? 'ar' : 'en').format(d);

// ---------------------------------------------------------------- the screen
enum _Tab { umrah, hajj, miqat, prayers, check }

/// Hajj & Umrah: a pushed screen with its own sky.
class PilgrimageScreen extends StatefulWidget {
  const PilgrimageScreen({super.key, required this.state});
  final AppState state;

  @override
  State<PilgrimageScreen> createState() => _PilgrimageScreenState();
}

class _PilgrimageScreenState extends State<PilgrimageScreen> {
  final _scroll = ScrollController();
  final _heroKey = GlobalKey();
  final _formKey = GlobalKey();
  _Tab _tab = _Tab.umrah;
  bool _compact = false; // the hero has scrolled away: the title moves into the top bar

  // API answers, shared by the hero and the prayer tab; a failed one is dropped on retry.
  final Map<String, Future<Map<String, dynamic>>> _prayerCache = {};
  Future<Map<String, dynamic>>? _hajjDates;

  // The prayer tab's choices.
  String _city = 'makkah';
  late String _start = isoDay(makkahNow());

  // The Umrah form lives here so typed values survive switching tabs.
  final _from = TextEditingController();
  final _budget = TextEditingController();
  late DateTime _depart = DateUtils.dateOnly(DateTime.now()).add(const Duration(days: 14));
  int _nights = 7, _makkah = 5, _pax = 2;
  bool _formError = false;

  @override
  void initState() {
    super.initState();
    _scroll.addListener(() {
      final c = _scroll.offset > 180;
      if (c != _compact) setState(() => _compact = c);
    });
  }

  @override
  void dispose() {
    _scroll.dispose();
    _from.dispose();
    _budget.dispose();
    super.dispose();
  }

  Future<Map<String, dynamic>> _prayers(String city, String start) => _prayerCache.putIfAbsent('$city|$start', () async {
        final r = await widget.state.api.get('/api/pilgrimage/prayer-times', query: {'city': city, 'start': start, 'days': '7'});
        final days = r is Map ? r['days'] : null;
        if (days is! Map || days.isEmpty) throw StateError('no prayer times');
        return Map<String, dynamic>.from(r as Map);
      });

  void _retryPrayers(String city, String start) => setState(() => _prayerCache.remove('$city|$start'));

  Future<Map<String, dynamic>> get _nextHajj => _hajjDates ??= () async {
        final r = await widget.state.api.get('/api/pilgrimage/hajj-dates');
        if (r is! Map || r['days'] is! Map) throw StateError('no hajj dates');
        return Map<String, dynamic>.from(r);
      }();

  void _setTab(_Tab t) {
    if (t == _tab) return;
    HapticFeedback.selectionClick();
    setState(() => _tab = t);
    // Past the hero, the new tab starts at its top (just under the pinned tabs), not in the middle.
    final heroH = _heroKey.currentContext?.size?.height;
    if (heroH != null && _scroll.hasClients && _scroll.offset > heroH) {
      _scroll.animateTo(heroH, duration: const Duration(milliseconds: 380), curve: Curves.easeOutCubic);
    }
  }

  void _swipe(DragEndDetails d) {
    final v = d.primaryVelocity ?? 0;
    if (v.abs() < 450) return;
    final rtl = Directionality.of(context) == TextDirection.rtl;
    final forward = rtl ? v > 0 : v < 0;
    final i = (_tab.index + (forward ? 1 : -1)).clamp(0, _Tab.values.length - 1);
    _setTab(_Tab.values[i]);
  }

  void _goToForm() {
    _setTab(_Tab.umrah);
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final c = _formKey.currentContext;
      if (c != null) {
        Scrollable.ensureVisible(c, duration: const Duration(milliseconds: 650), curve: Curves.easeInOutCubic, alignment: .08);
      }
    });
  }

  void _submit() {
    final from = _from.text.trim();
    if (from.isEmpty) {
      setState(() => _formError = true);
      HapticFeedback.heavyImpact();
      return;
    }
    final st = widget.state;
    if (st.busy) {
      toast(context, L('Dalili is still answering your last message - try again in a moment.',
          'دليلي لسه بيرد على رسالتك اللي فاتت - جرّب كمان شوية.'));
      return;
    }
    final msg = umrahMessage(
      arabic: isArabic, nights: _nights, makkah: _makkah, date: _fmt(_depart, 'd MMMM y'),
      pax: _pax, budget: _budget.text, from: from,
    );
    // An Umrah is a new trip: the open one stays saved in My trips.
    st.newTrip();
    st.goTab(Tabs.chat);
    Navigator.of(context).pop();
    st.send(msg);
  }

  @override
  Widget build(BuildContext context) {
    final dark = context.dark;
    final bottom = MediaQuery.viewPaddingOf(context).bottom;
    return Scaffold(
      backgroundColor: dark ? DC.night : DC.day,
      body: SkyBackground(
        planes: 0,
        glow: _green,
        child: Column(children: [
          _TopBar(compact: _compact),
          Expanded(
            child: CustomScrollView(
              controller: _scroll,
              slivers: [
                SliverToBoxAdapter(
                  child: KeyedSubtree(
                    key: _heroKey,
                    child: _Hero(
                      makkah: _prayers('makkah', isoDay(makkahNow())),
                      onRetry: () => _retryPrayers('makkah', isoDay(makkahNow())),
                      onPlan: _goToForm,
                    ),
                  ),
                ),
                SliverPersistentHeader(pinned: true, delegate: _TabsHeader(tab: _tab, onTab: _setTab, dark: dark)),
                SliverToBoxAdapter(
                  child: GestureDetector(
                    behavior: HitTestBehavior.translucent,
                    onHorizontalDragEnd: _swipe,
                    child: Padding(
                      padding: EdgeInsets.fromLTRB(16, 8, 16, bottom + 32),
                      // Only the new tab fades in (no cross-fade): the old one never lingers, so the form's key
                      // is never on screen twice.
                      child: _FadeIn(key: ValueKey(_tab), child: _body()),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ]),
      ),
    );
  }

  Widget _body() {
    final Widget content = switch (_tab) {
      _Tab.umrah => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _Journey(items: _umrah[_lang]!, stripNumbers: true, key: const ValueKey('umrah')),
          const SizedBox(height: 22),
          KeyedSubtree(key: _formKey, child: _umrahForm()),
        ]),
      _Tab.hajj => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _Notice(L('Hajj is explained here, never planned: it goes only through official channels.',
              'الحج هنا شرح بس، من غير تخطيط: الحج من القنوات الرسمية بس.')),
          const SizedBox(height: 14),
          _HajjDatesPass(future: _nextHajj,onRetry: () => setState(() => _hajjDates = null)),
          const SizedBox(height: 22),
          _Journey(items: _hajj[_lang]!, stripNumbers: false, key: const ValueKey('hajj')),
        ]),
      _Tab.miqat => _MiqatTab(items: _miqat[_lang]!),
      _Tab.prayers => _prayerTab(),
      _Tab.check => _Checklist(items: _check[_lang]!),
    };
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [content, const SizedBox(height: 24), const _Footer()]);
  }

  // ---------------------------------------------------------------- prayer times
  Widget _prayerTab() {
    final today = isoDay(makkahNow());
    final city = _city, start = _start;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      _CityToggle(city: city, onChanged: (c) {
        HapticFeedback.selectionClick();
        setState(() => _city = c);
      }),
      const SizedBox(height: 10),
      _FieldTile(
        icon: Icons.date_range_rounded,
        label: L('From', 'من يوم'),
        value: _fmt(DateTime.parse(start), 'EEEE d MMMM'),
        trailing: start == today ? null : L('Today', 'النهارده'),
        onTrailing: () => setState(() => _start = today),
        onTap: () async {
          final now = DateTime.parse(today);
          final d = await showDatePicker(
              context: context, initialDate: DateTime.parse(start), firstDate: now.subtract(const Duration(days: 30)),
              lastDate: now.add(const Duration(days: 730)));
          if (d != null && mounted) setState(() => _start = isoDay(d));
        },
      ),
      const SizedBox(height: 14),
      FutureBuilder<Map<String, dynamic>>(
        key: ValueKey('$city|$start'),
        future: _prayers(city, start),
        builder: (context, s) {
          if (s.hasError) return _Retry(onRetry: () => _retryPrayers(city, start));
          if (!s.hasData) return const _Loading(height: 420);
          final days = Map<String, dynamic>.from(s.data!['days'] as Map);
          return _PrayerWeek(days: days, today: today);
        },
      ),
      const SizedBox(height: 10),
      Text(L('Umm al-Qura method, as used in the two Holy Mosques.', 'بطريقة أم القرى، المعمول بها في الحرمين.'),
          style: TextStyle(fontSize: 12, color: context.muted)),
    ]);
  }

  // ---------------------------------------------------------------- the Umrah form (a pass)
  Widget _umrahForm() {
    final md = _nights - _makkah;
    final accent = _accent(context);
    return Ticket(
      gradient: LinearGradient(
        colors: context.dark ? const [Color(0xFF0E2A24), Color(0xFF101A2C)] : const [Color(0xFFFFFCF5), Color(0xFFF4EEDD)],
        begin: Alignment.topLeft, end: Alignment.bottomRight,
      ),
      borderColor: _gold.withValues(alpha: .35),
      main: Padding(
        padding: const EdgeInsets.fromLTRB(18, 18, 18, 14),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            const SizedBox(width: 40, height: 40, child: CustomPaint(painter: _KaabaGlyphPainter())),
            const SizedBox(width: 12),
            Expanded(child: Text(L('Plan my Umrah', 'خطّطلي عمرة'), style: display(size: 20, color: context.ink))),
            Text('UMRAH', style: mono(size: 11, color: accent, spacing: 2)),
          ]),
          const SizedBox(height: 8),
          Text(
            L("Flights, a hotel near the Haram, the Umrah on your first day in Makkah, the Prophet's Mosque in Madinah, and the prayer times on every day.",
                'طيران، فندق قريب من الحرم، العمرة في أول يوم في مكة، المسجد النبوي في المدينة، ومواقيت الصلاة كل يوم.'),
            style: TextStyle(fontSize: 13, height: 1.5, color: context.muted),
          ),
          const SizedBox(height: 16),
          TextField(
            controller: _from,
            textInputAction: TextInputAction.next,
            onChanged: (_) {
              if (_formError) setState(() => _formError = false);
            },
            decoration: InputDecoration(
              labelText: L('Flying from', 'مسافر من'),
              hintText: L('Cairo', 'القاهرة'),
              prefixIcon: const Icon(Icons.flight_takeoff_rounded),
              errorText: _formError ? L('Add where you fly from and the departure date.', 'اكتب مسافر منين وتاريخ السفر.') : null,
            ),
          ),
          const SizedBox(height: 10),
          _FieldTile(
            icon: Icons.edit_calendar_rounded,
            label: L('Departure', 'تاريخ السفر'),
            value: _fmt(_depart, 'EEEE d MMMM y'),
            onTap: () async {
              final today = DateUtils.dateOnly(DateTime.now());
              final d = await showDatePicker(
                  context: context, initialDate: _depart.isBefore(today) ? today : _depart, firstDate: today,
                  lastDate: today.add(const Duration(days: 730)));
              if (d != null && mounted) setState(() => _depart = d);
            },
          ),
          const SizedBox(height: 14),
          _Stepper(
            label: L('Nights', 'عدد الليالي'), value: _nights, min: 2, max: 30,
            onChanged: (v) => setState(() {
              _nights = v;
              _makkah = _makkah.clamp(1, v);
            }),
          ),
          const SizedBox(height: 8),
          _SplitBar(makkah: _makkah, madinah: md),
          SliderTheme(
            data: SliderTheme.of(context).copyWith(
              activeTrackColor: accent, thumbColor: accent, inactiveTrackColor: _green.withValues(alpha: .35),
              overlayColor: _gold.withValues(alpha: .15), trackHeight: 3,
            ),
            child: Slider(
              value: _makkah.toDouble(), min: 1, max: _nights.toDouble(), divisions: _nights - 1,
              semanticFormatterCallback: (v) => '${v.round()} ${L('in Makkah', 'في مكة')}',
              onChanged: (v) {
                if (v.round() != _makkah) HapticFeedback.selectionClick();
                setState(() => _makkah = v.round());
              },
            ),
          ),
          _Stepper(label: L('Travellers', 'عدد الأفراد'), value: _pax, min: 1, max: 9, onChanged: (v) => setState(() => _pax = v)),
          const SizedBox(height: 12),
          TextField(
            controller: _budget,
            textInputAction: TextInputAction.done,
            decoration: InputDecoration(
              labelText: L('Total budget', 'الميزانية الكلية'),
              hintText: '2,500 USD',
              prefixIcon: const Icon(Icons.account_balance_wallet_outlined),
            ),
          ),
        ]),
      ),
      stub: Padding(
        padding: const EdgeInsets.fromLTRB(18, 6, 18, 18),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Row(children: [
            Expanded(child: PassField(L('Nights', 'الليالي'), '$_nights', valueColor: accent)),
            Expanded(child: PassField(L('Makkah', 'مكة'), '$_makkah')),
            Expanded(child: PassField(L('Madinah', 'المدينة'), '$md')),
            Expanded(child: PassField(L('Pax', 'أفراد'), '$_pax', end: true)),
          ]),
          const SizedBox(height: 14),
          _HolyButton(label: L('Plan my Umrah', 'خطّطلي العمرة'), onTap: _submit),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- top bar + hero
class _TopBar extends StatelessWidget {
  const _TopBar({required this.compact});
  final bool compact;

  @override
  Widget build(BuildContext context) => SafeArea(
        bottom: false,
        child: SizedBox(
          height: 56,
          child: Row(children: [
            const SizedBox(width: 8),
            Container(
              decoration: BoxDecoration(color: context.card.withValues(alpha: .7), shape: BoxShape.circle, border: Border.all(color: context.line)),
              child: const BackButton(),
            ),
            const SizedBox(width: 10),
            Expanded(
              child: AnimatedOpacity(
                opacity: compact ? 1 : 0,
                duration: const Duration(milliseconds: 220),
                child: AnimatedSlide(
                  offset: compact ? Offset.zero : const Offset(0, .3),
                  duration: const Duration(milliseconds: 260),
                  curve: Curves.easeOutCubic,
                  child: Text(L('Hajj & Umrah', 'الحج والعمرة'), maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: display(size: 18, color: context.ink)),
                ),
              ),
            ),
            const SizedBox(width: 16),
          ]),
        ),
      );
}

class _Hero extends StatelessWidget {
  const _Hero({required this.makkah, required this.onRetry, required this.onPlan});
  final Future<Map<String, dynamic>> makkah;
  final VoidCallback onRetry;
  final VoidCallback onPlan;

  @override
  Widget build(BuildContext context) => Padding(
        padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
        child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          Reveal(
            child: ClipRRect(
              borderRadius: BorderRadius.circular(28),
              child: DecoratedBox(
                decoration: const BoxDecoration(
                  gradient: LinearGradient(colors: [_greenDeep, Color(0xFF0B4A3A), _greenDeep],
                      begin: Alignment.topLeft, end: Alignment.bottomRight),
                ),
                child: Stack(children: [
                  const Positioned.fill(child: RepaintBoundary(child: CustomPaint(painter: _PatternPainter()))),
                  Padding(
                    padding: const EdgeInsets.fromLTRB(20, 18, 20, 20),
                    child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                      const SizedBox(height: 150, child: _HolyScene()),
                      const SizedBox(height: 10),
                      Text(L('Hajj & Umrah', 'الحج والعمرة'), style: display(size: 30, color: _ivory, height: 1.1)),
                      const SizedBox(height: 6),
                      Text(
                        L('The rituals step by step, the miqat, prayer times in Makkah and Madinah, what to prepare - and an Umrah planned around the prayers, with a hotel close to the Haram.',
                            'المناسك خطوة بخطوة، المواقيت، مواقيت الصلاة في مكة والمدينة، وتجهّز إيه - وعمرة متخططة حوالين الصلوات، بفندق قريب من الحرم.'),
                        style: TextStyle(fontSize: 13.5, height: 1.55, color: _ivory.withValues(alpha: .78)),
                      ),
                      const SizedBox(height: 16),
                      Align(
                        alignment: AlignmentDirectional.centerStart,
                        child: Pressable(
                          onTap: onPlan,
                          child: Container(
                            constraints: const BoxConstraints(minHeight: 46),
                            padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 10),
                            decoration: BoxDecoration(
                              borderRadius: BorderRadius.circular(999),
                              border: Border.all(color: _gold.withValues(alpha: .7)),
                              color: _gold.withValues(alpha: .12),
                            ),
                            child: Row(mainAxisSize: MainAxisSize.min, children: [
                              const Icon(Icons.flight_takeoff_rounded, size: 18, color: _gold),
                              const SizedBox(width: 8),
                              Flexible(
                                child: Text(L('Plan my Umrah', 'خطّطلي عمرة'),
                                    style: const TextStyle(color: _gold, fontWeight: FontWeight.w800, fontSize: 14.5)),
                              ),
                            ]),
                          ),
                        ),
                      ),
                    ]),
                  ),
                ]),
              ),
            ),
          ),
          const SizedBox(height: 14),
          Reveal(
            delay: const Duration(milliseconds: 140),
            child: FutureBuilder<Map<String, dynamic>>(
              future: makkah,
              builder: (context, s) {
                if (s.hasError) return _Retry(onRetry: onRetry, compact: true);
                if (!s.hasData) return const _Loading(height: 112);
                return _NextPrayerPass(days: Map<String, dynamic>.from(s.data!['days'] as Map));
              },
            ),
          ),
        ]),
      );
}

/// The next prayer in Makkah, counting down each second (only this pass rebuilds).
class _NextPrayerPass extends StatefulWidget {
  const _NextPrayerPass({required this.days});
  final Map<String, dynamic> days;

  @override
  State<_NextPrayerPass> createState() => _NextPrayerPassState();
}

class _NextPrayerPassState extends State<_NextPrayerPass> {
  Timer? _t;

  @override
  void initState() {
    super.initState();
    _t = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    _t?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final now = makkahNow();
    final next = nextPrayer(widget.days, now);
    if (next == null) return const SizedBox.shrink();
    final accent = _accent(context);
    final hijri = (widget.days[isoDay(now)] as Map?)?['hijri'] as Map?;
    final hijriText = hijri == null ? null : '${hijri['day']} ${isArabic ? hijri['month_ar'] : hijri['month_en']} ${hijri['year']} ${L('AH', 'هـ')}';
    final hh = next.at.hour.toString().padLeft(2, '0'), mm = next.at.minute.toString().padLeft(2, '0');
    return Semantics(
      liveRegion: false,
      label: '${L('Next prayer in Makkah', 'الصلاة الجاية في مكة')}: ${_prayerName(next.key)} $hh:$mm',
      child: Tilt3D(
        maxAngle: .07,
        child: Ticket(
          axis: Axis.horizontal,
          borderColor: _gold.withValues(alpha: .3),
          main: Padding(
            padding: const EdgeInsets.fromLTRB(18, 16, 14, 16),
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
              Text(L('Next prayer in Makkah', 'الصلاة الجاية في مكة').toUpperCase(),
                  maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: TextStyle(fontSize: 10.5, letterSpacing: 1.1, fontWeight: FontWeight.w800, color: context.faint)),
              const SizedBox(height: 4),
              Row(crossAxisAlignment: CrossAxisAlignment.baseline, textBaseline: TextBaseline.alphabetic, children: [
                Flexible(
                  child: AnimatedSwitcher(
                    duration: const Duration(milliseconds: 500),
                    child: Text(_prayerName(next.key), key: ValueKey(next.key), maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: display(size: 26, color: accent, height: 1.15)),
                  ),
                ),
                const SizedBox(width: 10),
                Directionality(textDirection: TextDirection.ltr, child: Text('$hh:$mm', style: mono(size: 17, color: context.ink))),
              ]),
              if (hijriText != null) ...[
                const SizedBox(height: 4),
                Text(hijriText, maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12.5, color: context.muted)),
              ],
            ]),
          ),
          stub: SizedBox(
            width: 112,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 14),
              child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                Text(L('in', 'باقي'), style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: context.faint)),
                const SizedBox(height: 4),
                FittedBox(
                  fit: BoxFit.scaleDown,
                  child: Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text(countdownText(next.at.difference(now)), style: mono(size: 17, color: context.ink)),
                  ),
                ),
                const SizedBox(height: 4),
                Text(L('Makkah time', 'بتوقيت مكة'), maxLines: 1, overflow: TextOverflow.ellipsis,
                    style: TextStyle(fontSize: 10.5, color: context.faint)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// The hero's drawing: the Kaaba in the middle of the mataf, the arcades and two minarets behind, under a slowly
/// breathing glow. Drawn, not an image; the only motion is the glow.
class _HolyScene extends StatefulWidget {
  const _HolyScene();

  @override
  State<_HolyScene> createState() => _HolySceneState();
}

class _HolySceneState extends State<_HolyScene> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(seconds: 7))..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => RepaintBoundary(child: CustomPaint(painter: _HolyPainter(_c), size: Size.infinite));
}

class _HolyPainter extends CustomPainter {
  _HolyPainter(this.t) : super(repaint: t);
  final Animation<double> t;

  @override
  void paint(Canvas canvas, Size size) {
    final w = size.width, h = size.height;
    final cx = w / 2, ground = h * .84;
    final glow = .6 + .4 * Curves.easeInOut.transform(t.value);

    // The glow behind everything.
    final hc = Offset(cx, h * .46);
    canvas.drawCircle(hc, h * .62,
        Paint()..shader = ui.Gradient.radial(hc, h * .62, [_gold.withValues(alpha: .26 * glow), _gold.withValues(alpha: 0)]));

    // Minarets.
    final tower = Paint()..color = _ivory.withValues(alpha: .5);
    for (final x in [cx - math.min(w * .36, h * .95), cx + math.min(w * .36, h * .95)]) {
      final top = ground - h * .78;
      canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTRB(x - 4, top, x + 4, ground), const Radius.circular(2)), tower);
      for (final f in [.32, .55]) {
        final y = top + (ground - top) * f;
        canvas.drawRRect(RRect.fromRectAndRadius(Rect.fromLTRB(x - 7.5, y, x + 7.5, y + 3), const Radius.circular(1.5)), tower);
      }
      canvas.drawPath(Path()
        ..moveTo(x - 4, top)
        ..lineTo(x, top - 15)
        ..lineTo(x + 4, top)
        ..close(), tower);
      canvas.drawCircle(Offset(x, top - 17), 1.8, Paint()..color = _gold.withValues(alpha: .9));
    }

    // The arcades: a low row of arches along the horizon.
    final arch = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.1
      ..color = _ivory.withValues(alpha: .22);
    final aw = 13.0, ah = h * .12;
    for (var x = w * .08; x + aw <= w * .92; x += aw + 3) {
      canvas.drawPath(Path()
        ..moveTo(x, ground)
        ..lineTo(x, ground - ah)
        ..arcToPoint(Offset(x + aw, ground - ah), radius: Radius.circular(aw / 2))
        ..lineTo(x + aw, ground), arch);
    }

    // The mataf: soft rings around the Kaaba.
    for (final (i, a) in [(0, .30), (1, .18), (2, .10)]) {
      final rw = h * (.95 + i * .32);
      canvas.drawOval(Rect.fromCenter(center: Offset(cx, ground), width: rw, height: rw * .2), Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 1
        ..color = _gold.withValues(alpha: a));
    }

    // The Kaaba: front face, side face, roof, the gold band and the door.
    final fw = h * .40, fh = h * .44, dx = fw * .42, dy = fw * .16;
    final x0 = cx - (fw + dx) / 2, x1 = x0 + fw, y0 = ground - fh;
    canvas.drawOval(Rect.fromCenter(center: Offset(cx + dx * .2, ground + 2), width: fw * 1.9, height: fw * .22),
        Paint()..color = Colors.black.withValues(alpha: .35));
    final front = Rect.fromLTRB(x0, y0, x1, ground);
    canvas.drawRect(front, Paint()..shader = ui.Gradient.linear(front.topCenter, front.bottomCenter, const [Color(0xFF1E1E22), Color(0xFF09090B)]));
    final side = Path()
      ..moveTo(x1, y0)
      ..lineTo(x1 + dx, y0 - dy)
      ..lineTo(x1 + dx, ground - dy)
      ..lineTo(x1, ground)
      ..close();
    canvas.drawPath(side, Paint()..color = const Color(0xFF050506));
    canvas.drawPath(Path()
      ..moveTo(x0, y0)
      ..lineTo(x1, y0)
      ..lineTo(x1 + dx, y0 - dy)
      ..lineTo(x0 + dx, y0 - dy)
      ..close(), Paint()..color = const Color(0xFF2A2A30));
    final b0 = y0 + fh * .17, b1 = y0 + fh * .27;
    final band = Paint()..shader = ui.Gradient.linear(Offset(x0, b0), Offset(x1 + dx, b0), const [_gold, Color(0xFFF4DDA4), _gold], const [0, .5, 1]);
    canvas.drawRect(Rect.fromLTRB(x0, b0, x1, b1), band);
    canvas.drawPath(Path()
      ..moveTo(x1, b0)
      ..lineTo(x1 + dx, b0 - dy)
      ..lineTo(x1 + dx, b1 - dy)
      ..lineTo(x1, b1)
      ..close(), Paint()..color = _goldDeep);
    // The band's script, suggested by fine strokes.
    final script = Paint()
      ..color = const Color(0xFF7A5A1C).withValues(alpha: .7)
      ..strokeWidth = .8;
    for (var x = x0 + 3; x < x1 - 3; x += 4) {
      canvas.drawLine(Offset(x, b0 + (b1 - b0) * .3), Offset(x + 2, b0 + (b1 - b0) * .7), script);
    }
    final door = Rect.fromLTRB(x0 + fw * .6, ground - fh * .58, x0 + fw * .8, ground - fh * .2);
    canvas.drawRect(door, Paint()..shader = ui.Gradient.linear(door.topLeft, door.bottomRight, const [Color(0xFFF1D79A), _goldDeep]));
    canvas.drawLine(door.topCenter, door.bottomCenter, Paint()
      ..color = const Color(0xFF6B4E16)
      ..strokeWidth = .8);
    canvas.drawLine(Offset(x1, y0), Offset(x1, ground), Paint()
      ..color = Colors.white.withValues(alpha: .07)
      ..strokeWidth = 1);
  }

  @override
  bool shouldRepaint(_HolyPainter old) => false;
}

/// A faint lattice of eight-pointed stars on the hero's green.
class _PatternPainter extends CustomPainter {
  const _PatternPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = .8
      ..color = _gold.withValues(alpha: .08);
    const step = 38.0, r = 11.0;
    for (var y = step / 2; y < size.height + step; y += step) {
      for (var x = step / 2; x < size.width + step; x += step) {
        final c = Offset(x, y);
        canvas.drawRect(Rect.fromCenter(center: c, width: r * 2, height: r * 2), p);
        canvas.save();
        canvas.translate(c.dx, c.dy);
        canvas.rotate(math.pi / 4);
        canvas.drawRect(Rect.fromCenter(center: Offset.zero, width: r * 2, height: r * 2), p);
        canvas.restore();
      }
    }
  }

  @override
  bool shouldRepaint(_PatternPainter old) => false;
}

/// A small Kaaba for the form's header.
class _KaabaGlyphPainter extends CustomPainter {
  const _KaabaGlyphPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final s = size.width;
    canvas.drawRRect(RRect.fromRectAndRadius(Offset.zero & size, Radius.circular(s * .28)), Paint()..color = _greenDeep);
    final f = Rect.fromLTWH(s * .22, s * .3, s * .42, s * .46);
    canvas.drawRect(f, Paint()..color = const Color(0xFF111114));
    canvas.drawPath(Path()
      ..moveTo(f.right, f.top)
      ..lineTo(f.right + s * .16, f.top - s * .07)
      ..lineTo(f.right + s * .16, f.bottom - s * .07)
      ..lineTo(f.right, f.bottom)
      ..close(), Paint()..color = const Color(0xFF050506));
    canvas.drawRect(Rect.fromLTWH(f.left, f.top + f.height * .17, f.width, f.height * .11), Paint()..color = _gold);
    canvas.drawRect(Rect.fromLTWH(f.left + f.width * .6, f.top + f.height * .45, f.width * .2, f.height * .38), Paint()..color = _gold);
  }

  @override
  bool shouldRepaint(_KaabaGlyphPainter old) => false;
}

// ---------------------------------------------------------------- tabs
class _TabsHeader extends SliverPersistentHeaderDelegate {
  _TabsHeader({required this.tab, required this.onTab, required this.dark});
  final _Tab tab;
  final ValueChanged<_Tab> onTab;
  final bool dark;

  static const _h = 64.0;

  @override
  double get minExtent => _h;
  @override
  double get maxExtent => _h;

  @override
  bool shouldRebuild(_TabsHeader old) => old.tab != tab || old.dark != dark;

  @override
  Widget build(BuildContext context, double shrinkOffset, bool overlapsContent) {
    final labels = {
      _Tab.umrah: L('Umrah', 'العمرة'),
      _Tab.hajj: L('Hajj', 'الحج'),
      _Tab.miqat: L('Miqat', 'المواقيت'),
      _Tab.prayers: L('Prayer times', 'مواقيت الصلاة'),
      _Tab.check: L('Checklist', 'تجهيزات'),
    };
    final pinned = overlapsContent || shrinkOffset > 0;
    return AnimatedContainer(
      duration: const Duration(milliseconds: 220),
      decoration: BoxDecoration(
        color: pinned ? (dark ? DC.night : DC.day).withValues(alpha: .94) : Colors.transparent,
        border: Border(bottom: BorderSide(color: pinned ? context.line : Colors.transparent)),
      ),
      child: ListView(
        scrollDirection: Axis.horizontal,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
        children: [
          for (final t in _Tab.values) ...[
            _Seg(label: labels[t]!, selected: t == tab, onTap: () => onTab(t)),
            const SizedBox(width: 8),
          ],
        ],
      ),
    );
  }
}

class _Seg extends StatelessWidget {
  const _Seg({required this.label, required this.selected, required this.onTap});
  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Semantics(
        selected: selected,
        button: true,
        child: Pressable(
          onTap: onTap,
          haptic: false,
          child: AnimatedContainer(
            duration: const Duration(milliseconds: 280),
            curve: Curves.easeOutCubic,
            constraints: const BoxConstraints(minHeight: 44, minWidth: 44),
            padding: const EdgeInsets.symmetric(horizontal: 16),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(999),
              gradient: selected ? const LinearGradient(colors: [_green, _greenDeep]) : null,
              color: selected ? null : context.card.withValues(alpha: .85),
              border: Border.all(color: selected ? _gold.withValues(alpha: .7) : context.line),
              boxShadow: selected ? [BoxShadow(color: _green.withValues(alpha: .35), blurRadius: 14, offset: const Offset(0, 4))] : null,
            ),
            child: Text(label,
                style: TextStyle(
                    fontSize: 14, fontWeight: FontWeight.w700, color: selected ? _ivory : context.muted)),
          ),
        ),
      );
}

// ---------------------------------------------------------------- the steps as a journey of passes
/// The rituals as a column of passes on a gold rail: open one to read it all; the rail fills up to the step you
/// are on, and "Next step" walks you through.
class _Journey extends StatefulWidget {
  const _Journey({super.key, required this.items, required this.stripNumbers});
  final List<(String, String)> items;
  final bool stripNumbers; // Umrah: the number moves onto the stub

  @override
  State<_Journey> createState() => _JourneyState();
}

class _JourneyState extends State<_Journey> {
  int _open = 0;
  int _reached = 0;

  void _toggle(int i) {
    HapticFeedback.selectionClick();
    setState(() {
      if (_open == i) {
        _open = -1;
      } else {
        _open = i;
        _reached = i;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    final n = widget.items.length;
    final accent = _accent(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      if (widget.stripNumbers) ...[
        Row(children: [
          Expanded(
            child: Text(L('The Umrah, step by step', 'العمرة خطوة بخطوة'), style: display(size: 18, color: context.ink)),
          ),
          Directionality(
            textDirection: TextDirection.ltr,
            child: Text('${_reached + 1}/$n', style: mono(size: 13, color: accent)),
          ),
        ]),
        const SizedBox(height: 8),
        ClipRRect(
          borderRadius: BorderRadius.circular(99),
          child: TweenAnimationBuilder<double>(
            tween: Tween(end: (_reached + 1) / n),
            duration: const Duration(milliseconds: 600),
            curve: Curves.easeOutCubic,
            builder: (_, v, _) => LinearProgressIndicator(value: v, minHeight: 4, color: accent, backgroundColor: context.line),
          ),
        ),
        const SizedBox(height: 16),
      ],
      for (var i = 0; i < n; i++)
        Reveal(
          delay: Duration(milliseconds: 60 * i),
          child: _StepPass(
            item: widget.items[i],
            index: i,
            first: i == 0,
            last: i == n - 1,
            open: _open == i,
            passed: i <= _reached,
            linePassed: i < _reached,
            stripNumber: widget.stripNumbers,
            onTap: () => _toggle(i),
            onNext: i < n - 1 ? () => _toggle(i + 1) : null,
          ),
        ),
    ]);
  }
}

class _StepPass extends StatelessWidget {
  const _StepPass({
    required this.item, required this.index, required this.first, required this.last, required this.open,
    required this.passed, required this.linePassed, required this.stripNumber, required this.onTap, this.onNext,
  });
  final (String, String) item;
  final int index;
  final bool first, last, open, passed, linePassed, stripNumber;
  final VoidCallback onTap;
  final VoidCallback? onNext;

  @override
  Widget build(BuildContext context) {
    final accent = _accent(context);
    final (no, title) = stripNumber ? _splitNumber(item.$1) : (_splitNumber(item.$1).$1, item.$1);
    final badge = no ?? '✦';
    return Stack(children: [
      Padding(
        padding: EdgeInsetsDirectional.only(start: 30, bottom: last ? 0 : 12),
        child: Semantics(
          button: true,
          expanded: open,
          child: Pressable(
            onTap: onTap,
            haptic: false,
            scale: .985,
            child: Ticket(
              axis: Axis.horizontal,
              radius: 18,
              notch: 10,
              gap: 16,
              elevation: open ? 10 : 4,
              borderColor: open ? _gold.withValues(alpha: .45) : null,
              main: Padding(
                padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, mainAxisSize: MainAxisSize.min, children: [
                  Text(title, style: display(size: 16, color: open ? accent : context.ink, height: 1.3)),
                  const SizedBox(height: 6),
                  AnimatedSize(
                    duration: const Duration(milliseconds: 320),
                    curve: Curves.easeOutCubic,
                    alignment: AlignmentDirectional.topStart,
                    child: Text(item.$2,
                        maxLines: open ? null : 2,
                        overflow: open ? TextOverflow.visible : TextOverflow.ellipsis,
                        style: TextStyle(fontSize: 14, height: 1.65, color: open ? context.ink : context.muted)),
                  ),
                  if (open && onNext != null) ...[
                    const SizedBox(height: 10),
                    Align(
                      alignment: AlignmentDirectional.centerEnd,
                      child: TextButton(
                        onPressed: onNext,
                        style: TextButton.styleFrom(foregroundColor: accent, minimumSize: const Size(44, 44)),
                        child: Text(L('Next step', 'الخطوة الجاية'), style: const TextStyle(fontWeight: FontWeight.w800)),
                      ),
                    ),
                  ],
                ]),
              ),
              stub: SizedBox(
                width: 58,
                child: Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                  FittedBox(
                    fit: BoxFit.scaleDown,
                    child: Text(badge, style: display(size: no != null && no.length > 2 ? 16 : 24, color: accent, weight: FontWeight.w700)),
                  ),
                  const SizedBox(height: 4),
                  AnimatedRotation(
                    turns: open ? .5 : 0,
                    duration: const Duration(milliseconds: 300),
                    child: Icon(Icons.expand_more_rounded, size: 20, color: context.faint),
                  ),
                ]),
              ),
            ),
          ),
        ),
      ),
      PositionedDirectional(
        start: 0,
        top: 0,
        bottom: 0,
        width: 30,
        child: TweenAnimationBuilder<double>(
          tween: Tween(end: passed ? 1 : 0),
          duration: const Duration(milliseconds: 420),
          builder: (_, a, _) => TweenAnimationBuilder<double>(
            tween: Tween(end: linePassed ? 1 : 0),
            duration: const Duration(milliseconds: 420),
            builder: (_, b, _) => CustomPaint(
              painter: _RailPainter(first: first, last: last, node: a, below: b, gold: accent, track: context.line, ring: context.faint),
            ),
          ),
        ),
      ),
    ]);
  }
}

class _RailPainter extends CustomPainter {
  _RailPainter({required this.first, required this.last, required this.node, required this.below, required this.gold,
      required this.track, required this.ring});
  final bool first, last;
  final double node, below; // 0..1: this step reached / the line to the next one walked
  final Color gold, track, ring;

  @override
  void paint(Canvas canvas, Size size) {
    final x = size.width / 2 - 4;
    const y = 30.0;
    final line = Paint()
      ..strokeWidth = 2
      ..strokeCap = StrokeCap.round;
    if (!first) canvas.drawLine(Offset(x, 0), Offset(x, y), line..color = Color.lerp(track, gold, node)!);
    if (!last) canvas.drawLine(Offset(x, y), Offset(x, size.height), line..color = Color.lerp(track, gold, below)!);
    canvas.drawCircle(Offset(x, y), 10 * node, Paint()..color = gold.withValues(alpha: .16 * node));
    canvas.drawCircle(Offset(x, y), 5.5, Paint()..color = Color.lerp(Colors.transparent, gold, node)!);
    canvas.drawCircle(Offset(x, y), 5.5, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.6
      ..color = Color.lerp(ring, gold, node)!);
  }

  @override
  bool shouldRepaint(_RailPainter o) =>
      o.node != node || o.below != below || o.first != first || o.last != last || o.gold != gold || o.track != track;
}

// ---------------------------------------------------------------- Hajj: the next Hajj as a pass
class _HajjDatesPass extends StatelessWidget {
  const _HajjDatesPass({required this.future, required this.onRetry});
  final Future<Map<String, dynamic>> future;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) => FutureBuilder<Map<String, dynamic>>(
        future: future,
        builder: (context, s) {
          if (s.hasError) return _Retry(onRetry: onRetry);
          if (!s.hasData) return const _Loading(height: 300);
          final year = s.data!['hijri_year'];
          final raw = Map<String, dynamic>.from(s.data!['days'] as Map);
          final days = <int, DateTime>{
            for (final e in raw.entries)
              if (int.tryParse(e.key) != null && _parseDay('${e.value}') != null) int.parse(e.key): _parseDay('${e.value}')!,
          };
          if (days.isEmpty) return _Retry(onRetry: onRetry);
          final keys = days.keys.toList()..sort();
          final today = DateTime.parse(isoDay(makkahNow()));
          final arafah = days[9];
          final until = arafah?.difference(today).inDays;
          // The day names come from the guidance titles themselves ("9 Dhu al-Hijjah · Arafah").
          final titles = _hajj[_lang]!;
          String? dayName(int d) {
            final i = switch (d) { 8 => 1, 9 => 2, 10 => 4, 11 || 12 || 13 => 5, _ => -1 };
            if (i < 0) return null;
            return _cap(titles[i].$1.split(' · ').last);
          }

          const white = _ivory;
          final soft = _ivory.withValues(alpha: .7);
          return Tilt3D(
            maxAngle: .06,
            child: Ticket(
              gradient: const LinearGradient(colors: [_green, _greenDeep], begin: Alignment.topLeft, end: Alignment.bottomRight),
              borderColor: _gold.withValues(alpha: .45),
              dashColor: _gold.withValues(alpha: .4),
              main: Stack(children: [
                const Positioned.fill(child: CustomPaint(painter: _PatternPainter())),
                Padding(
                  padding: const EdgeInsets.fromLTRB(20, 18, 20, 16),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    Row(children: [
                      Expanded(
                        child: Text(L('Expected dates of Hajj $year AH', 'المواعيد المتوقعة لحج $year هـ'),
                            style: display(size: 15, color: white, height: 1.3)),
                      ),
                      if (until != null && until > 0) Pill(L('in $until days', 'بعد $until يوم'), color: _gold),
                    ]),
                    const SizedBox(height: 14),
                    Row(crossAxisAlignment: CrossAxisAlignment.end, children: [
                      Expanded(child: _HajjEnd(day: keys.first, date: days[keys.first]!, end: false)),
                      const Padding(
                        padding: EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                        child: SizedBox(width: 48, height: 24, child: CustomPaint(painter: _DotsPainter())),
                      ),
                      Expanded(child: _HajjEnd(day: keys.last, date: days[keys.last]!, end: true)),
                    ]),
                    if (arafah != null) ...[
                      const SizedBox(height: 14),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                        decoration: BoxDecoration(
                          color: _gold.withValues(alpha: .14),
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: _gold.withValues(alpha: .4)),
                        ),
                        child: Row(children: [
                          Expanded(
                            child: Text(dayName(9) ?? '', style: const TextStyle(color: _gold, fontWeight: FontWeight.w800)),
                          ),
                          Flexible(
                            child: Text(_fmt(arafah, 'EEEE d MMMM y'), textAlign: TextAlign.end,
                                style: const TextStyle(color: white, fontWeight: FontWeight.w700)),
                          ),
                        ]),
                      ),
                    ],
                  ]),
                ),
              ]),
              stub: Padding(
                padding: const EdgeInsets.fromLTRB(20, 4, 20, 18),
                child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  for (final d in keys)
                    Padding(
                      padding: const EdgeInsets.symmetric(vertical: 5),
                      child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                        SizedBox(
                          width: 34,
                          child: Text('$d', style: mono(size: 16, color: d == 9 ? _gold : white)),
                        ),
                        Expanded(
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Text(L('$d Dhu al-Hijjah', '$d ذو الحجة'),
                                style: TextStyle(fontSize: 13.5, fontWeight: FontWeight.w700, color: d == 9 ? _gold : white)),
                            if (dayName(d) != null) Text(dayName(d)!, style: TextStyle(fontSize: 12, color: soft)),
                          ]),
                        ),
                        const SizedBox(width: 8),
                        Flexible(
                          child: Text(_fmt(days[d]!, 'EEE d MMM'), textAlign: TextAlign.end,
                              style: const TextStyle(fontSize: 13, color: white, fontWeight: FontWeight.w600)),
                        ),
                      ]),
                    ),
                  const SizedBox(height: 10),
                  Text(L('By the Umm al-Qura calendar; the moon sighting can move them by a day.',
                      'حسب تقويم أم القرى؛ رؤية الهلال ممكن تغيّرها يوم.'), style: TextStyle(fontSize: 12, color: soft, height: 1.5)),
                  const SizedBox(height: 12),
                  Barcode('HAJJ-$year', height: 36, color: _ivory.withValues(alpha: .75)),
                ]),
              ),
            ),
          );
        },
      );
}

class _HajjEnd extends StatelessWidget {
  const _HajjEnd({required this.day, required this.date, required this.end});
  final int day;
  final DateTime date;
  final bool end;

  @override
  Widget build(BuildContext context) => Column(
        crossAxisAlignment: end ? CrossAxisAlignment.end : CrossAxisAlignment.start,
        children: [
          Text(L('$day Dhu al-Hijjah', '$day ذو الحجة').toUpperCase(),
              maxLines: 1, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 10.5, letterSpacing: 1, fontWeight: FontWeight.w800, color: _ivory.withValues(alpha: .6))),
          const SizedBox(height: 4),
          FittedBox(
            fit: BoxFit.scaleDown,
            child: Text(_fmt(date, 'd MMM'), style: display(size: 26, color: _ivory, height: 1.1)),
          ),
          Text(_fmt(date, 'EEEE · y'), maxLines: 1, overflow: TextOverflow.ellipsis,
              style: TextStyle(fontSize: 12, color: _ivory.withValues(alpha: .7))),
        ],
      );
}

/// The dotted path between the first and last day on the Hajj pass.
class _DotsPainter extends CustomPainter {
  const _DotsPainter();

  @override
  void paint(Canvas canvas, Size size) {
    final p = Paint()..color = _gold.withValues(alpha: .7);
    final y = size.height / 2;
    for (var x = 2.0; x < size.width - 8; x += 6) {
      canvas.drawCircle(Offset(x, y), 1.3, p);
    }
    canvas.drawCircle(Offset(size.width - 4, y), 3.2, p);
  }

  @override
  bool shouldRepaint(_DotsPainter old) => false;
}

// ---------------------------------------------------------------- miqat
class _MiqatTab extends StatefulWidget {
  const _MiqatTab({required this.items});
  final List<(String, String)> items;

  @override
  State<_MiqatTab> createState() => _MiqatTabState();
}

class _MiqatTabState extends State<_MiqatTab> {
  int? _sel;

  void _pick(int i) {
    HapticFeedback.selectionClick();
    setState(() => _sel = _sel == i ? null : i);
  }

  @override
  Widget build(BuildContext context) {
    final items = widget.items;
    final places = items.take(_miqatBearing.length).toList();
    final notes = items.skip(_miqatBearing.length).toList();
    final accent = _accent(context);
    final dist = RegExp(r'([0-9٠-٩]+)\s*(km|كم)');
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Reveal(
        child: Container(
          height: 260,
          decoration: BoxDecoration(
            color: context.ticket,
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: context.ticketEdge),
          ),
          child: RepaintBoundary(
            child: LayoutBuilder(
              builder: (context, c) => GestureDetector(
                onTapUp: (d) {
                  final hit = _MiqatMapPainter.hit(c.biggest, d.localPosition);
                  if (hit != null) _pick(hit);
                },
                child: CustomPaint(
                  painter: _MiqatMapPainter(
                    names: [for (final p in places) p.$1.split(' (').first],
                    selected: _sel, ink: context.ink, muted: context.muted, line: context.line, gold: accent,
                    makkah: L('Makkah', 'مكة'), north: L('N', 'ش'),
                  ),
                  size: c.biggest,
                ),
              ),
            ),
          ),
        ),
      ),
      const SizedBox(height: 16),
      for (var i = 0; i < places.length; i++)
        Reveal(
          delay: Duration(milliseconds: 60 * (i + 1)),
          child: Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Pressable(
              onTap: () => _pick(i),
              haptic: false,
              scale: .985,
              child: Ticket(
                axis: Axis.horizontal,
                radius: 18,
                notch: 10,
                gap: 16,
                elevation: _sel == i ? 10 : 4,
                borderColor: _sel == i ? _gold.withValues(alpha: .5) : null,
                main: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 14, 12, 14),
                  child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                    Text(places[i].$1, style: display(size: 16, color: _sel == i ? accent : context.ink, height: 1.3)),
                    const SizedBox(height: 6),
                    Text(places[i].$2, style: TextStyle(fontSize: 14, height: 1.6, color: context.muted)),
                  ]),
                ),
                stub: SizedBox(
                  width: 70,
                  child: Builder(builder: (context) {
                    final m = dist.firstMatch(places[i].$2);
                    return Column(mainAxisAlignment: MainAxisAlignment.center, children: [
                      FittedBox(
                        fit: BoxFit.scaleDown,
                        child: Text(m?[1] ?? '–', style: display(size: 22, color: accent)),
                      ),
                      Text(m?[2] ?? '', style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700, color: context.faint)),
                    ]);
                  }),
                ),
              ),
            ),
          ),
        ),
      for (var i = 0; i < notes.length; i++)
        Reveal(
          delay: Duration(milliseconds: 60 * (places.length + i + 1)),
          child: Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: _NoteCard(
              icon: i == 0 ? Icons.flight_rounded : Icons.place_rounded,
              title: notes[i].$1,
              text: notes[i].$2,
            ),
          ),
        ),
    ]);
  }
}

/// A compass map: Makkah in the middle, the five miqats at their real bearings (north up, never mirrored), the
/// distance drawn on a square-root scale so the near ones don't crowd the centre.
class _MiqatMapPainter extends CustomPainter {
  _MiqatMapPainter({required this.names, required this.selected, required this.ink, required this.muted,
      required this.line, required this.gold, required this.makkah, required this.north});
  final List<String> names;
  final int? selected;
  final Color ink, muted, line, gold;
  final String makkah, north;

  static double _radius(Size s) => math.min(s.width, s.height) / 2 - 30;

  static Offset _at(Size s, int i) {
    final (deg, km) = _miqatBearing[i];
    final r = _radius(s) * math.sqrt(km / 420);
    final a = deg * math.pi / 180;
    return s.center(Offset.zero) + Offset(math.sin(a) * r, -math.cos(a) * r);
  }

  static int? hit(Size s, Offset p) {
    for (var i = 0; i < _miqatBearing.length; i++) {
      if ((_at(s, i) - p).distance < 26) return i;
    }
    return null;
  }

  void _label(Canvas canvas, String text, Offset at, TextStyle style, {bool above = false}) {
    final tp = TextPainter(text: TextSpan(text: text, style: style), textDirection: isArabic ? TextDirection.rtl : TextDirection.ltr,
        maxLines: 1, ellipsis: '…')
      ..layout(maxWidth: 120);
    tp.paint(canvas, Offset(at.dx - tp.width / 2, above ? at.dy - tp.height - 8 : at.dy + 8));
  }

  @override
  void paint(Canvas canvas, Size size) {
    final c = size.center(Offset.zero);
    final rr = _radius(size);
    final ringP = Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1
      ..color = line;
    for (final km in [75.0, 186.0, 420.0]) {
      canvas.drawCircle(c, rr * math.sqrt(km / 420), ringP);
    }
    canvas.drawLine(c - Offset(0, rr + 8), c + Offset(0, rr + 8), ringP);
    _label(canvas, north, c - Offset(0, rr + 6), TextStyle(fontSize: 10, fontWeight: FontWeight.w800, color: muted), above: true);
    for (var i = 0; i < _miqatBearing.length; i++) {
      final p = _at(size, i);
      final on = selected == i;
      canvas.drawLine(c, p, Paint()
        ..strokeWidth = on ? 1.8 : 1
        ..color = gold.withValues(alpha: on ? .9 : .35));
      if (on) canvas.drawCircle(p, 13, Paint()..color = gold.withValues(alpha: .18));
      canvas.drawCircle(p, on ? 6 : 4.5, Paint()..color = gold);
      _label(canvas, names[i], p, TextStyle(fontSize: 11, fontWeight: on ? FontWeight.w800 : FontWeight.w600, color: on ? ink : muted),
          above: p.dy < c.dy);
    }
    // Makkah: a tiny Kaaba.
    canvas.drawRect(Rect.fromCenter(center: c, width: 12, height: 12), Paint()..color = const Color(0xFF111114));
    canvas.drawRect(Rect.fromLTWH(c.dx - 6, c.dy - 3.5, 12, 2), Paint()..color = _gold);
    _label(canvas, makkah, c + const Offset(0, 4), TextStyle(fontSize: 11.5, fontWeight: FontWeight.w800, color: ink));
  }

  @override
  bool shouldRepaint(_MiqatMapPainter o) =>
      o.selected != selected || o.ink != ink || o.gold != gold || o.makkah != makkah || o.names.join() != names.join();
}

// ---------------------------------------------------------------- prayer times
class _CityToggle extends StatelessWidget {
  const _CityToggle({required this.city, required this.onChanged});
  final String city;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    final cities = [('makkah', L('Makkah', 'مكة المكرمة')), ('madinah', L('Madinah', 'المدينة المنورة'))];
    return Container(
      height: 52,
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: context.card.withValues(alpha: .9),
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: context.line),
      ),
      child: Stack(children: [
        AnimatedAlign(
          alignment: city == 'makkah' ? AlignmentDirectional.centerStart : AlignmentDirectional.centerEnd,
          duration: const Duration(milliseconds: 360),
          curve: Curves.easeOutCubic,
          child: FractionallySizedBox(
            widthFactor: .5,
            heightFactor: 1,
            child: DecoratedBox(
              decoration: BoxDecoration(
                borderRadius: BorderRadius.circular(999),
                gradient: const LinearGradient(colors: [_green, _greenDeep]),
                border: Border.all(color: _gold.withValues(alpha: .6)),
              ),
            ),
          ),
        ),
        Row(children: [
          for (final (k, label) in cities)
            Expanded(
              child: Semantics(
                selected: city == k,
                button: true,
                child: GestureDetector(
                  behavior: HitTestBehavior.opaque,
                  onTap: () => city == k ? null : onChanged(k),
                  child: Center(
                    child: AnimatedDefaultTextStyle(
                      duration: const Duration(milliseconds: 260),
                      style: TextStyle(fontSize: 14, fontWeight: FontWeight.w800, color: city == k ? _ivory : context.muted,
                          fontFamily: DefaultTextStyle.of(context).style.fontFamily),
                      child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis),
                    ),
                  ),
                ),
              ),
            ),
        ]),
      ]),
    );
  }
}

class _PrayerWeek extends StatelessWidget {
  const _PrayerWeek({required this.days, required this.today});
  final Map<String, dynamic> days;
  final String today;

  @override
  Widget build(BuildContext context) {
    final keys = days.keys.toList()..sort();
    final next = nextPrayer(days, makkahNow());
    final accent = _accent(context);
    final names = _prayerNames[_lang]!;
    Widget cells(List<Widget> children) => Row(children: [for (final c in children) Expanded(child: c)]);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Padding(
        padding: const EdgeInsets.symmetric(horizontal: 12),
        child: cells([
          for (final n in names)
            FittedBox(
              fit: BoxFit.scaleDown,
              child: Text(n, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: context.faint)),
            ),
        ]),
      ),
      const SizedBox(height: 8),
      for (var i = 0; i < keys.length; i++)
        Reveal(
          delay: Duration(milliseconds: 45 * i),
          child: Builder(builder: (context) {
            final iso = keys[i];
            final v = days[iso] as Map;
            final times = (v['times'] as Map?) ?? const {};
            final hijri = v['hijri'] as Map?;
            final d = DateTime.parse(iso);
            final isToday = iso == today;
            return Container(
              margin: const EdgeInsets.only(bottom: 8),
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 12),
              decoration: BoxDecoration(
                color: isToday ? null : context.ticket.withValues(alpha: .92),
                gradient: isToday
                    ? LinearGradient(
                        colors: context.dark ? const [Color(0xFF0F3A30), Color(0xFF111A2E)] : const [Color(0xFFFFF7E6), Color(0xFFF3EBD6)],
                        begin: Alignment.topLeft, end: Alignment.bottomRight)
                    : null,
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: isToday ? _gold.withValues(alpha: .55) : context.ticketEdge, width: isToday ? 1.4 : 1),
              ),
              child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Row(children: [
                  Flexible(
                    child: Text(_fmt(d, 'EEE d MMM'), maxLines: 1, overflow: TextOverflow.ellipsis,
                        style: display(size: 14.5, color: context.ink)),
                  ),
                  if (hijri != null) ...[
                    const SizedBox(width: 8),
                    Flexible(
                      child: Text('${hijri['day']} ${isArabic ? hijri['month_ar'] : hijri['month_en']}',
                          maxLines: 1, overflow: TextOverflow.ellipsis, style: TextStyle(fontSize: 12, color: context.muted)),
                    ),
                  ],
                  const Spacer(),
                  if (isToday) Pill(L('Today', 'النهارده'), color: accent),
                ]),
                const SizedBox(height: 8),
                cells([
                  for (final k in _prayerKeys)
                    Builder(builder: (context) {
                      final isNext = next != null && next.day == iso && next.key == k;
                      return Container(
                        margin: const EdgeInsets.symmetric(horizontal: 2),
                        padding: const EdgeInsets.symmetric(vertical: 6),
                        decoration: BoxDecoration(
                          color: isNext ? accent : Colors.transparent,
                          borderRadius: BorderRadius.circular(10),
                        ),
                        child: FittedBox(
                          fit: BoxFit.scaleDown,
                          child: Text('${times[k] ?? '–'}',
                              style: mono(size: 14, weight: isNext ? FontWeight.w800 : FontWeight.w600,
                                  color: isNext ? (context.dark ? DC.night : Colors.white) : context.ink)),
                        ),
                      );
                    }),
                ]),
              ]),
            );
          }),
        ),
    ]);
  }
}

// ---------------------------------------------------------------- checklist
class _Checklist extends StatefulWidget {
  const _Checklist({required this.items});
  final List<String> items;

  @override
  State<_Checklist> createState() => _ChecklistState();
}

class _ChecklistState extends State<_Checklist> {
  SharedPreferences? _prefs;
  final Set<int> _done = {};

  @override
  void initState() {
    super.initState();
    SharedPreferences.getInstance().then((p) {
      if (!mounted) return;
      setState(() {
        _prefs = p;
        for (var i = 0; i < widget.items.length; i++) {
          if (p.getBool('pg_check_$i') ?? false) _done.add(i);
        }
      });
    });
  }

  // By position, so a tick stays when the language changes.
  void _toggle(int i) {
    HapticFeedback.selectionClick();
    setState(() => _done.contains(i) ? _done.remove(i) : _done.add(i));
    _prefs?.setBool('pg_check_$i', _done.contains(i));
  }

  void _clear() {
    setState(_done.clear);
    for (var i = 0; i < widget.items.length; i++) {
      _prefs?.remove('pg_check_$i');
    }
  }

  @override
  Widget build(BuildContext context) {
    final n = widget.items.length;
    final accent = _accent(context);
    final all = _done.length == n;
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: context.ticket,
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: all ? _gold.withValues(alpha: .55) : context.ticketEdge),
        ),
        child: Row(children: [
          SizedBox(
            width: 76,
            height: 76,
            child: TweenAnimationBuilder<double>(
              tween: Tween(end: n == 0 ? 0 : _done.length / n),
              duration: const Duration(milliseconds: 650),
              curve: Curves.easeOutCubic,
              builder: (_, v, _) => CustomPaint(
                painter: _RingPainter(v, accent, context.line),
                child: Center(
                  child: Directionality(
                    textDirection: TextDirection.ltr,
                    child: Text('${_done.length}/$n', style: mono(size: 16, color: context.ink)),
                  ),
                ),
              ),
            ),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(all ? L('All ready', 'كله جاهز') : L('What to prepare', 'تجهّز إيه'),
                  style: display(size: 18, color: all ? accent : context.ink)),
              const SizedBox(height: 2),
              Text(L('Tick what you have ready - it stays on this phone.', 'علّم على اللي جهّزته - بيفضل محفوظ على الموبايل ده.'),
                  style: TextStyle(fontSize: 12.5, height: 1.45, color: context.muted)),
            ]),
          ),
          if (_done.isNotEmpty)
            IconButton(
              tooltip: L('Clear all', 'امسح الكل'),
              onPressed: _clear,
              icon: Icon(Icons.refresh_rounded, color: context.faint),
            ),
        ]),
      ),
      const SizedBox(height: 14),
      for (var i = 0; i < n; i++)
        Reveal(
          delay: Duration(milliseconds: 45 * i),
          child: Padding(
            padding: const EdgeInsets.only(bottom: 8),
            child: Semantics(
              checked: _done.contains(i),
              child: Pressable(
                onTap: () => _toggle(i),
                haptic: false,
                scale: .98,
                child: AnimatedContainer(
                  duration: const Duration(milliseconds: 260),
                  constraints: const BoxConstraints(minHeight: 52),
                  padding: const EdgeInsets.fromLTRB(12, 12, 14, 12),
                  decoration: BoxDecoration(
                    color: _done.contains(i) ? accent.withValues(alpha: context.dark ? .10 : .08) : context.ticket.withValues(alpha: .92),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: _done.contains(i) ? accent.withValues(alpha: .45) : context.ticketEdge),
                  ),
                  child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                    AnimatedContainer(
                      duration: const Duration(milliseconds: 260),
                      curve: Curves.easeOutBack,
                      width: 26,
                      height: 26,
                      decoration: BoxDecoration(
                        shape: BoxShape.circle,
                        color: _done.contains(i) ? accent : Colors.transparent,
                        border: Border.all(color: _done.contains(i) ? accent : context.faint, width: 1.6),
                      ),
                      child: AnimatedScale(
                        scale: _done.contains(i) ? 1 : 0,
                        duration: const Duration(milliseconds: 260),
                        curve: Curves.easeOutBack,
                        child: Icon(Icons.check_rounded, size: 17, color: context.dark ? DC.night : Colors.white),
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: AnimatedDefaultTextStyle(
                        duration: const Duration(milliseconds: 260),
                        style: TextStyle(fontSize: 14, height: 1.55, color: _done.contains(i) ? context.muted : context.ink,
                            fontFamily: DefaultTextStyle.of(context).style.fontFamily),
                        child: Text(widget.items[i]),
                      ),
                    ),
                  ]),
                ),
              ),
            ),
          ),
        ),
    ]);
  }
}

class _RingPainter extends CustomPainter {
  _RingPainter(this.v, this.color, this.track);
  final double v;
  final Color color, track;

  @override
  void paint(Canvas canvas, Size size) {
    final r = Rect.fromCircle(center: size.center(Offset.zero), radius: size.width / 2 - 5);
    canvas.drawArc(r, 0, math.pi * 2, false, Paint()
      ..style = PaintingStyle.stroke
      ..strokeWidth = 6
      ..color = track);
    if (v > 0) {
      canvas.drawArc(r, -math.pi / 2, math.pi * 2 * v, false, Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 6
        ..strokeCap = StrokeCap.round
        ..color = color);
    }
  }

  @override
  bool shouldRepaint(_RingPainter o) => o.v != v || o.color != color || o.track != track;
}

// ---------------------------------------------------------------- small pieces
class _Notice extends StatelessWidget {
  const _Notice(this.text);
  final String text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 12),
        decoration: BoxDecoration(
          color: _green.withValues(alpha: context.dark ? .18 : .08),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: _green.withValues(alpha: .35)),
        ),
        child: Text(text, style: TextStyle(fontSize: 13.5, height: 1.5, color: context.ink, fontWeight: FontWeight.w600)),
      );
}

class _NoteCard extends StatelessWidget {
  const _NoteCard({required this.icon, required this.title, required this.text});
  final IconData icon;
  final String title, text;

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: context.card2.withValues(alpha: .9),
          borderRadius: BorderRadius.circular(18),
          border: Border.all(color: context.line),
        ),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(color: _gold.withValues(alpha: .16), shape: BoxShape.circle),
            child: Icon(icon, size: 18, color: _accent(context)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: display(size: 15.5, color: context.ink, height: 1.3)),
              const SizedBox(height: 4),
              Text(text, style: TextStyle(fontSize: 14, height: 1.6, color: context.muted)),
            ]),
          ),
        ]),
      );
}

class _FieldTile extends StatelessWidget {
  const _FieldTile({required this.icon, required this.label, required this.value, required this.onTap, this.trailing, this.onTrailing});
  final IconData icon;
  final String label, value;
  final VoidCallback onTap;
  final String? trailing;
  final VoidCallback? onTrailing;

  @override
  Widget build(BuildContext context) => Material(
        color: context.dark ? const Color(0xFF0B1222) : Colors.white,
        borderRadius: BorderRadius.circular(16),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(16),
          child: Container(
            constraints: const BoxConstraints(minHeight: 56),
            padding: const EdgeInsetsDirectional.fromSTEB(12, 8, 6, 8),
            decoration: BoxDecoration(borderRadius: BorderRadius.circular(16), border: Border.all(color: context.line)),
            child: Row(children: [
              Icon(icon, size: 22, color: context.muted),
              const SizedBox(width: 12),
              Expanded(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, mainAxisSize: MainAxisSize.min, children: [
                  Text(label, style: TextStyle(fontSize: 11.5, color: context.faint, fontWeight: FontWeight.w700)),
                  const SizedBox(height: 2),
                  Text(value, maxLines: 1, overflow: TextOverflow.ellipsis,
                      style: TextStyle(fontSize: 15, color: context.ink, fontWeight: FontWeight.w700)),
                ]),
              ),
              if (trailing != null)
                TextButton(onPressed: onTrailing, style: TextButton.styleFrom(minimumSize: const Size(44, 44)), child: Text(trailing!)),
            ]),
          ),
        ),
      );
}

class _Stepper extends StatelessWidget {
  const _Stepper({required this.label, required this.value, required this.min, required this.max, required this.onChanged});
  final String label;
  final int value, min, max;
  final ValueChanged<int> onChanged;

  @override
  Widget build(BuildContext context) {
    Widget btn(IconData icon, int to, bool on) => SizedBox(
          width: 44,
          height: 44,
          child: IconButton.outlined(
            onPressed: on
                ? () {
                    HapticFeedback.selectionClick();
                    onChanged(to);
                  }
                : null,
            icon: Icon(icon, size: 20),
          ),
        );
    return Row(children: [
      Expanded(child: Text(label, style: TextStyle(fontSize: 14.5, fontWeight: FontWeight.w700, color: context.ink))),
      btn(Icons.remove_rounded, value - 1, value > min),
      SizedBox(
        width: 44,
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 200),
          transitionBuilder: (c, a) => FadeTransition(opacity: a, child: ScaleTransition(scale: a, child: c)),
          child: Text('$value', key: ValueKey(value), textAlign: TextAlign.center, style: mono(size: 18, color: context.ink)),
        ),
      ),
      btn(Icons.add_rounded, value + 1, value < max),
    ]);
  }
}

/// How the nights split between the two cities.
class _SplitBar extends StatelessWidget {
  const _SplitBar({required this.makkah, required this.madinah});
  final int makkah, madinah;

  @override
  Widget build(BuildContext context) {
    final accent = _accent(context);
    return Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
      Row(children: [
        Expanded(
          child: Text('$makkah ${L('in Makkah', 'في مكة')}',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: accent)),
        ),
        Expanded(
          child: Text(madinah > 0 ? '$madinah ${L('in Madinah', 'في المدينة')}' : L('Makkah only', 'مكة بس'),
              textAlign: TextAlign.end, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w800, color: _green)),
        ),
      ]),
      const SizedBox(height: 6),
      ClipRRect(
        borderRadius: BorderRadius.circular(99),
        child: SizedBox(
          height: 8,
          child: Row(children: [
            Expanded(flex: makkah, child: ColoredBox(color: accent)),
            if (madinah > 0) ...[
              const SizedBox(width: 3),
              Expanded(flex: madinah, child: const ColoredBox(color: _green)),
            ],
          ]),
        ),
      ),
    ]);
  }
}

class _HolyButton extends StatelessWidget {
  const _HolyButton({required this.label, required this.onTap});
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) => Pressable(
        onTap: onTap,
        child: Container(
          height: 54,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            gradient: const LinearGradient(colors: [_green, _greenDeep]),
            borderRadius: BorderRadius.circular(16),
            border: Border.all(color: _gold.withValues(alpha: .7)),
            boxShadow: [BoxShadow(color: _green.withValues(alpha: .35), blurRadius: 20, offset: const Offset(0, 8))],
          ),
          child: Row(mainAxisSize: MainAxisSize.min, children: [
            const Icon(Icons.auto_awesome_rounded, size: 18, color: _gold),
            const SizedBox(width: 8),
            Flexible(
              child: Text(label, maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: const TextStyle(color: _ivory, fontWeight: FontWeight.w800, fontSize: 16)),
            ),
          ]),
        ),
      );
}

/// A tab's content arriving: fades up a little, once.
class _FadeIn extends StatefulWidget {
  const _FadeIn({super.key, required this.child});
  final Widget child;

  @override
  State<_FadeIn> createState() => _FadeInState();
}

class _FadeInState extends State<_FadeIn> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 420))..forward();

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => AnimatedBuilder(
        animation: _c,
        builder: (_, child) {
          final v = Curves.easeOutCubic.transform(_c.value);
          return Opacity(opacity: v, child: Transform.translate(offset: Offset(0, (1 - v) * 18), child: child));
        },
        child: widget.child,
      );
}

class _Loading extends StatefulWidget {
  const _Loading({required this.height});
  final double height;

  @override
  State<_Loading> createState() => _LoadingState();
}

class _LoadingState extends State<_Loading> with SingleTickerProviderStateMixin {
  late final AnimationController _c = AnimationController(vsync: this, duration: const Duration(milliseconds: 1300))..repeat(reverse: true);

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => FadeTransition(
        opacity: Tween(begin: .45, end: .9).animate(_c),
        child: Container(
          height: widget.height,
          alignment: Alignment.center,
          decoration: BoxDecoration(
            color: context.ticket.withValues(alpha: .8),
            borderRadius: BorderRadius.circular(22),
            border: Border.all(color: context.ticketEdge),
          ),
          child: Text(L('Loading…', 'بيحمّل…'), style: TextStyle(color: context.muted, fontWeight: FontWeight.w600)),
        ),
      );
}

class _Retry extends StatelessWidget {
  const _Retry({required this.onRetry, this.compact = false});
  final VoidCallback onRetry;
  final bool compact;

  @override
  Widget build(BuildContext context) => Container(
        padding: EdgeInsets.all(compact ? 14 : 20),
        decoration: BoxDecoration(
          color: context.ticket.withValues(alpha: .9),
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: context.ticketEdge),
        ),
        child: Row(children: [
          Expanded(
            child: Text(L("Couldn't load right now - try again.", 'معرفتش أحمّل دلوقتي - جرّب تاني.'),
                style: TextStyle(color: context.muted, height: 1.45)),
          ),
          const SizedBox(width: 10),
          OutlinedButton(onPressed: onRetry, child: Text(L('Try again', 'جرّب تاني'))),
        ]),
      );
}

/// The note on where the guidance comes from, and the official sources.
class _Footer extends StatelessWidget {
  const _Footer();

  @override
  Widget build(BuildContext context) => Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(
          L('General guidance following the widely published practice (Saudi Ministry of Hajj and Umrah, Nusuk). For a ruling about your own case, ask a scholar you trust.',
              'إرشادات عامة على المعمول به والمنشور (وزارة الحج والعمرة السعودية، منصة نسك). لحكم يخص حالتك، اسأل عالم تثق فيه.'),
          style: TextStyle(fontSize: 12.5, height: 1.55, color: context.muted),
        ),
        const SizedBox(height: 12),
        Text(L('Official sources', 'مصادر رسمية'), style: TextStyle(fontSize: 12, fontWeight: FontWeight.w800, color: context.faint)),
        const SizedBox(height: 6),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final (label, url) in [('Nusuk', _nusuk), (L('Ministry of Hajj and Umrah', 'وزارة الحج والعمرة'), _ministry)])
            OutlinedButton.icon(
              onPressed: () => openLink(url),
              icon: const Icon(Icons.open_in_new_rounded, size: 16),
              label: Text(label),
            ),
        ]),
      ]);
}
