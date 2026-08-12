/**
 * Creates the public Google Form described by google-form-spec.json.
 *
 * This script creates the Form only. It intentionally does not link a
 * response spreadsheet: Google Forms creates a new response tab when linked,
 * so that step must be completed deliberately per forms/README.md.
 */
function createGmailSupportAssistantForm() {
  const form = FormApp.create(
    'お問い合わせフォーム | Gmail Support Assistant Demo'
  );

  form
    .setDescription(
      '製品・配送・返金・技術的な問題に関するお問い合わせを受け付けます。' +
      '入力内容は、回答案の作成とサポート対応のためにGoogle Sheets、Make、' +
      'OpenAI、Slack、Gmailで処理されます。送信前に個人情報や機密情報を' +
      '必要以上に記載していないことをご確認ください。AIが作成した返信案は' +
      '自動送信されず、担当者が確認します。'
    )
    .setConfirmationMessage(
      'お問い合わせを受け付けました。担当者が内容を確認します。' +
      'AIが作成した返信案が自動送信されることはありません。'
    )
    .setCollectEmail(false)
    .setLimitOneResponsePerUser(false)
    .setProgressBar(false)
    .setShuffleQuestions(false)
    .setShowLinkToRespondAgain(false)
    .setPublishingSummary(false);

  const nameValidation = FormApp.createTextValidation()
    .requireTextLengthGreaterThanOrEqualTo(1)
    .requireTextLengthLessThanOrEqualTo(100)
    .build();
  form.addTextItem()
    .setTitle('Name')
    .setHelpText('お名前。例：山田 太郎（100文字以内）')
    .setRequired(true)
    .setValidation(nameValidation);

  const emailValidation = FormApp.createTextValidation()
    .requireTextIsEmail()
    .build();
  form.addTextItem()
    .setTitle('Email')
    .setHelpText('返信先メールアドレス。担当者からの返信を受け取れるアドレスを入力してください。')
    .setRequired(true)
    .setValidation(emailValidation);

  const subjectValidation = FormApp.createTextValidation()
    .requireTextLengthGreaterThanOrEqualTo(1)
    .requireTextLengthLessThanOrEqualTo(150)
    .build();
  form.addTextItem()
    .setTitle('Subject')
    .setHelpText('件名。例：届いた商品が破損していました（150文字以内）')
    .setRequired(true)
    .setValidation(subjectValidation);

  const messageValidation = FormApp.createParagraphTextValidation()
    .requireTextLengthGreaterThanOrEqualTo(1)
    .requireTextLengthLessThanOrEqualTo(5000)
    .build();
  form.addParagraphTextItem()
    .setTitle('Message')
    .setHelpText(
      'お問い合わせ内容。注文番号、発生日時、希望する対応などを具体的に' +
      '入力してください。パスワードや決済情報は入力しないでください。' +
      '（5000文字以内）'
    )
    .setRequired(true)
    .setValidation(messageValidation);

  console.log('Edit URL: ' + form.getEditUrl());
  console.log('Responder URL: ' + form.getPublishedUrl());
  console.log('Next: follow forms/README.md to link and verify the response sheet.');
}
