# Gmailカスタマーサポート支援

[English](README.en.md)

問い合わせをAIで分類し、CRM記録、Slack通知、Gmail返信下書きまでをつなぐカスタマーサポート自動化です。返信は**下書きとして作成するだけ**で、自動送信しません。最終確認と送信は必ず人が行います。

Google Forms、Google Sheets、Make.com、OpenAI、Slack、Gmailを組み合わせています。このリポジトリは、実際に構築・検証したワークフローからアカウント固有情報と顧客データを除いた公開版です。

> **安全上の重要な設計:** Gmailで行うのは下書き作成だけです。AIが顧客へ直接メールを送ることはありません。

## 解決する業務課題

問い合わせ対応では、内容の把握、優先度判断、CRMへの転記、社内共有、返信案の作成が繰り返し発生します。単純な直列自動化では、途中失敗後の再実行によって、すでに成功したCRM記録やSlack通知が重複する問題もあります。

このプロジェクトでは、次の方針で対応します。

- AIがカテゴリ、優先度、感情、人による対応の要否を構造化JSONで返す
- CRM記録、Slack通知、Gmail下書きを一つの処理フローにまとめる
- `Processing_State` と完了フラグで、再実行時に成功済みの副作用をスキップする
- Gmailは下書き専用とし、人が内容を確認して送信する

## システム概要

1. 顧客がGoogle Formから問い合わせを送信
2. Make.comがGoogle Sheetsの新規行を検知し、安定したRequest IDを生成
3. 既存の処理状態を確認し、完了済みの重複リクエストを停止
4. 保存済みAI結果がなければ、OpenAIが問い合わせを分類して返信案を生成
5. Google SheetsのCRMタブに処理結果を記録
6. Slackへ担当者向けの要約を通知
7. Gmailに返信下書きを作成
8. 各完了フラグを保存し、再実行時の重複処理を防止

![Gmail Support Assistantのシステム構成](docs/diagrams/system-architecture.svg)

詳細は[アーキテクチャ](docs/architecture.md)、[データモデル](docs/data-model.md)、[冪等性とエラー処理](docs/error-handling-and-idempotency.md)を参照してください。

## AI・ルール・人の責任分担

| 担当 | 役割 |
|---|---|
| AI | 問い合わせの分類、優先度・感情・人対応要否の判定、返信案の作成 |
| 決定的ルール | 入力検証、Request ID、処理状態、完了フラグ、再実行時のスキップ、Gmail下書き作成 |
| 人 | AI出力と顧客情報の確認、必要な修正、最終的な送信判断 |

AIの出力は業務判断の補助です。送信や例外対応の最終責任をAIに委ねる設計ではありません。

## 信頼性と安全性

- Gmail返信は自動送信せず、下書きとして作成します。
- OpenAIには顧客のメールアドレスを送信しません。
- OpenAI Responses APIの `store` と `createConversation` は `false` です。
- Phase 2Bでは処理状態と副作用ごとの完了フラグを保持し、観測した完了済みリプレイを入口で停止しました。
- 公開Blueprint、サンプルデータ、図には実アカウントID、認証情報、実顧客データを含めていません。
- 異常系の一部は未完成のまま明示的にブロックしており、厳密なexactly-once処理は保証していません。

実行時には、氏名・件名・本文がOpenAIへ送信され、Slackには氏名、メールアドレス、AI要約、返信案が送信されます。導入前に[セキュリティ方針](SECURITY.md)と[制約事項](docs/limitations.md)を確認してください。

## 検証済みの証拠

Phase 2B候補を実際のMakeシナリオで実行し、合成データを用いて次の結果を確認しました。

| 確認項目 | 観測結果 |
|---|---|
| Google Formの入力契約 | `Timestamp, Name, Email, Subject, Message` の正確なヘッダー |
| Form起点の初回実行 | 26 Makeオペレーションで全経路が完了 |
| 処理状態 | `COMPLETED`、AI・CRM・Slack・Gmailの各フラグがtrue |
| Gmailの安全境界 | 下書き1件を作成、メール送信なし |
| 同一Request IDの再実行 | 6つの制御・ゲート処理後に停止 |
| 重複する副作用 | CRM行、Slackモジュール実行、Gmail下書きの重複なし |

SlackについてはMakeの実行履歴と `Slack_Notified` フラグによる確認であり、Slack UI上のメッセージは独立確認していません。検証範囲と未確認事項は[実行時検証記録](docs/runtime-verification.md)に分離して記録しています。

![合成データによる公開用エンドツーエンドデモ](assets/demo/synthetic-e2e-demo.svg)

この図は `example.com` の合成データを使った再構成であり、非公開アカウントのスクリーンショットではありません。

## 公開成果物で再現できること

構造検証はAPIを呼び出さずに実行できます。

```bash
python3 tests/validate_blueprint.py
```

ライブ環境で再現する場合は、公開済みのPhase 2B Blueprintをインポートして各サービスを再接続し、[セットアップ手順](docs/setup.md)と[デプロイ確認表](make/phase2b-deployment-checklist.md)に従ってください。シナリオはInactiveのまま、合成データで `Run once` を使い、Gmailが送信ではなく下書きを作成したことを確認します。

## 技術構成

- Google Forms / Google Sheets
- Make.com
- OpenAI Responses API（Structured Outputs / JSON Schema）
- Slack
- Gmail
- Pythonによるオフライン構造検証

## リポジトリの主な内容

- [`make/blueprints/`](make/blueprints/) — サニタイズ済みのPhase 2A / Phase 2B Blueprint
- [`prompts/`](prompts/) — バージョン管理されたプロンプトとJSON Schema
- [`tests/`](tests/) — APIを呼び出さない構造検証と13件の評価ケース仕様
- [`docs/`](docs/) — 設計、セットアップ、検証記録、制約事項
- [`spreadsheet/templates/`](spreadsheet/templates/) — ヘッダーのみの3シート構成テンプレート
- [`sample_data/`](sample_data/) — `example.com` の合成サンプル
- [`forms/`](forms/) — Google Form仕様と作成用Apps Script

## 現在の制約

このプロジェクトは本番運用可能とは主張していません。正常系と完了済みリプレイはライブ検証済みですが、異常時の再取得、複数一致、検証通知、障害復旧の一部経路はブロックされています。新規アカウントへの移植、並行・大量実行、レート制限、長期運用も未検証です。

完全な一覧は[制約事項](docs/limitations.md)を参照してください。

## 公開範囲とプライバシー

このリポジトリは公開用にサニタイズされています。元のBlueprint、実スプレッドシート、接続ID、Webhook URL、認証情報、実顧客データは含みません。公開時の取り扱いと除外対象は[セキュリティ方針](SECURITY.md)と[マッピングガイド](make/mapping-guide.md)に記載しています。

## ライセンス

[MIT License](LICENSE)
