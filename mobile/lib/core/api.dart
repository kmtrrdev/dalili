import 'dart:async';
import 'dart:convert';

import 'package:http/http.dart' as http;

/// A problem the server reported (or a network failure: status 0).
class ApiException implements Exception {
  ApiException(this.status, this.message, {this.field});
  final int status;
  final String message;
  final String? field;
  @override
  String toString() => message;
}

/// One live step of a chat turn (from the server-sent events of /api/chat/stream).
class StreamEvent {
  StreamEvent(this.type, this.data);
  final String type; // node | tool | done | error
  final Map<String, dynamic> data;
}

/// Talks to the Dalili backend. The app signs in with a bearer token and keeps its own guest id,
/// so nothing relies on cookies.
class Api {
  Api({required this.baseUrl, required this.guestId, this.token});

  String baseUrl;
  String guestId;
  String? token;
  final http.Client _client = http.Client();

  Map<String, String> get _headers => {
        'Content-Type': 'application/json',
        'X-Client': 'mobile',
        'X-Guest-Id': guestId,
        if (token != null) 'Authorization': 'Bearer $token',
      };

  Uri _uri(String path, [Map<String, String>? query]) =>
      Uri.parse('${baseUrl.replaceAll(RegExp(r'/+$'), '')}$path').replace(queryParameters: query);

  Future<dynamic> _send(String method, String path, {Object? body, Map<String, String>? query,
      Duration timeout = const Duration(seconds: 40)}) async {
    final req = http.Request(method, _uri(path, query))..headers.addAll(_headers);
    if (body != null) req.body = jsonEncode(body);
    http.Response res;
    try {
      res = await http.Response.fromStream(await _client.send(req).timeout(timeout));
    } on TimeoutException {
      throw ApiException(0, 'timeout');
    } catch (_) {
      throw ApiException(0, 'network');
    }
    dynamic data;
    try {
      data = res.body.isEmpty ? null : jsonDecode(utf8.decode(res.bodyBytes));
    } catch (_) {
      data = null;
    }
    if (res.statusCode >= 400) {
      final detail = data is Map ? data['detail'] : null;
      throw ApiException(res.statusCode, detail is String ? detail : 'HTTP ${res.statusCode}',
          field: data is Map ? data['field'] as String? : null);
    }
    return data;
  }

  Future<dynamic> get(String path, {Map<String, String>? query}) => _send('GET', path, query: query);
  Future<dynamic> post(String path, [Object? body, Duration timeout = const Duration(seconds: 40)]) =>
      _send('POST', path, body: body ?? {}, timeout: timeout);
  Future<dynamic> patch(String path, Object body) => _send('PATCH', path, body: body);
  Future<dynamic> delete(String path, {Object? body, Map<String, String>? query}) =>
      _send('DELETE', path, body: body, query: query);

  /// A chat turn with live progress: node / tool events, then `done` with the reply and the full trip.
  Stream<StreamEvent> chatStream(String message, {String? tripId}) async* {
    final req = http.Request('POST', _uri('/api/chat/stream'))
      ..headers.addAll(_headers)
      ..body = jsonEncode({'message': message, 'trip_id': ?tripId});
    http.StreamedResponse res;
    try {
      res = await _client.send(req).timeout(const Duration(seconds: 30));
    } catch (_) {
      yield StreamEvent('error', {'message': 'network'});
      return;
    }
    if (res.statusCode >= 400) {
      yield StreamEvent('error', {'message': 'HTTP ${res.statusCode}'});
      return;
    }
    final lines = res.stream.transform(utf8.decoder).transform(const LineSplitter());
    try {
      await for (final line in lines.timeout(const Duration(minutes: 6))) {
        if (!line.startsWith('data: ')) continue;
        final ev = jsonDecode(line.substring(6)) as Map<String, dynamic>;
        yield StreamEvent(ev['type'] as String? ?? 'node', ev);
      }
    } on TimeoutException {
      yield StreamEvent('error', {'message': 'timeout'});
    } catch (_) {
      yield StreamEvent('error', {'message': 'network'});
    }
  }
}
