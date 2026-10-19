"""Auditable, factual-claim-free multilingual commercial copy for autonomous sends.

Gemini may propose alternatives, but only this catalog (or explicitly approved copy)
can be sent. Business identity, source and verified preview are injected by code.
"""

from website_agent.ai import EmailCopy

CATALOG = {
    "en": [
        "An independent website concept",
        "I prepared an independent, unofficial website redesign concept for your business.",
        "Would you like to discuss a website redesign?",
        "Following up on the independent website concept I shared.",
        "Thank you for your reply. I will pass it to the owner for review.",
    ],
    "hi": [
        "आपकी वेबसाइट के लिए एक स्वतंत्र डिज़ाइन अवधारणा",
        "मैंने आपके व्यवसाय के लिए एक स्वतंत्र, अनौपचारिक वेबसाइट डिज़ाइन अवधारणा तैयार की है।",
        "क्या आप वेबसाइट के नए डिज़ाइन पर चर्चा करना चाहेंगे?",
        "मैं पहले भेजी गई स्वतंत्र वेबसाइट अवधारणा के बारे में संपर्क कर रहा हूँ।",
        "आपके उत्तर के लिए धन्यवाद। मैं इसे समीक्षा के लिए मालिक तक पहुँचाऊँगा।",
    ],
    "ar": [
        "تصور مستقل لتصميم موقعكم",
        "أعددت تصوراً مستقلاً وغير رسمي لإعادة تصميم موقع نشاطكم التجاري.",
        "هل ترغبون في مناقشة إعادة تصميم الموقع؟",
        "أتابع معكم بشأن التصور المستقل للموقع الذي أرسلته سابقاً.",
        "شكراً لردكم. سأحيله إلى المالك للمراجعة.",
    ],
    "de": [
        "Ein unabhängiger Website-Entwurf",
        "Ich habe einen unabhängigen, inoffiziellen Website-Entwurf für Ihr Unternehmen erstellt.",
        "Möchten Sie über eine Neugestaltung Ihrer Website sprechen?",
        "Ich melde mich zu dem unabhängigen Website-Entwurf, den ich Ihnen geschickt habe.",
        "Vielen Dank für Ihre Antwort. Ich leite sie zur Prüfung an den Inhaber weiter.",
    ],
    "fr": [
        "Un concept indépendant pour votre site",
        "J’ai préparé un concept indépendant et non officiel de refonte du site de votre entreprise.",
        "Souhaitez-vous discuter d’une refonte de votre site ?",
        "Je reviens vers vous au sujet du concept indépendant de site envoyé précédemment.",
        "Merci pour votre réponse. Je la transmettrai au responsable pour examen.",
    ],
    "ja": [
        "独立したウェブサイトのデザイン案",
        "貴社向けに、独立した非公式のウェブサイト再設計案を作成しました。",
        "ウェブサイトの再設計についてお話ししませんか。",
        "先日お送りした独立したウェブサイトのデザイン案についてご連絡します。",
        "ご返信ありがとうございます。確認のため担当者にお伝えします。",
    ],
}


def trusted_copy(language, kind):
    subject, opening, invitation, followup, acknowledgment = CATALOG.get(
        language.split("-")[0], CATALOG["en"]
    )
    if kind == "followup":
        opening = followup
    elif kind == "acknowledgment":
        opening, invitation = acknowledgment, ""
    return EmailCopy(subject=subject, opening=opening, invitation=invitation or "Thank you.")
