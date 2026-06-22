"""
Seed Data — Populates the database with realistic demo data.

Creates ~50 ingested posts across all 4 platforms and ~30 draft comments
with realistic AI-generated responses referencing BCI financial schemes.
Mix of statuses: pending, posted, rejected, queued.

Usage:
    python seed_data.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from datetime import datetime, timezone, timedelta
from random import randint, choice
from api.database import init_db, SessionLocal, IngestedPost, DraftComment, PipelineRun

# ── Sample Data ──────────────────────────────────────────────────

REDDIT_POSTS = [
    {"title": "Best mutual fund for a 25-year-old beginner?", "text": "I'm 25 and just started earning. I have about 10k per month to invest. I'm confused between SIPs and lump sum. What would you recommend for someone with a moderate risk appetite? I've heard about index funds but not sure if they're good for India.", "source": "r/IndiaInvestments", "author": "u/young_investor_25"},
    {"title": "Home loan vs paying rent — what makes more financial sense?", "text": "I'm paying 25k rent in Bangalore. My friend says I should take a home loan instead since EMI would be similar. But I've heard property prices might fall. Should I take a home loan now or wait? What's the best home loan rate currently?", "source": "r/personalfinanceindia", "author": "u/bangalore_renter"},
    {"title": "Which credit card has the best rewards in India?", "text": "I spend about 50k per month on dining, fuel, and online shopping. Currently using a basic HDFC card but the rewards are terrible. Looking for a card with good cashback or lounge access. Budget for annual fee is up to 5k.", "source": "r/CreditCardsIndia", "author": "u/reward_hunter"},
    {"title": "Is NPS worth it for tax saving?", "text": "I already max out my 80C with ELSS. Should I put additional 50k in NPS for 80CCD(1B) deduction? I've heard the lock-in till 60 is a big downside. Is the extra tax saving worth the illiquidity?", "source": "r/IndiaInvestments", "author": "u/tax_optimizer"},
    {"title": "Term insurance — how much cover do I need?", "text": "I'm 30, married, one kid. Earning 15L per year. How much term insurance cover should I take? I've been getting quotes from various companies but the premium difference is huge. What factors should I consider?", "source": "r/personalfinanceindia", "author": "u/family_planner30"},
    {"title": "ELSS vs PPF for long-term wealth creation", "text": "I want to invest 1.5L per year for tax saving. Should I go with ELSS mutual funds or PPF? I have a 15+ year horizon. Which gives better returns historically? Also open to suggestions for good ELSS funds.", "source": "r/IndiaInvestments", "author": "u/wealth_builder"},
    {"title": "Should I prepay my home loan or invest in mutual funds?", "text": "I have a home loan at 8.5% interest and 20L surplus. Should I prepay the loan or invest in equity mutual funds for potentially higher returns? My loan tenure is 20 years remaining.", "source": "r/personalfinanceindia", "author": "u/loan_dilemma"},
    {"title": "Fixed deposit vs debt mutual fund — which is safer?", "text": "I have 5L emergency fund currently in savings account. Should I move it to a fixed deposit or a liquid mutual fund? I want safety first but also decent returns. What's the current FD rate?", "source": "r/IndiaInvestments", "author": "u/safety_first_investor"},
    {"title": "Health insurance for parents above 60", "text": "My parents are 62 and 58. They don't have any health insurance. I want to get them covered. Most plans seem expensive for senior citizens. Any recommendations for affordable plans with good coverage?", "source": "r/personalfinanceindia", "author": "u/caring_son"},
    {"title": "SIP of 5000 per month — where to invest?", "text": "I can invest 5000 per month via SIP. I'm 28 with a 10-year horizon. Should I go with a large cap, mid cap, or flexi cap fund? I want good growth but not too risky. Any specific fund recommendations?", "source": "r/mutualfunds", "author": "u/sip_starter"},
    {"title": "How to build a diversified portfolio with 50k/month?", "text": "I earn well and can invest 50k monthly. Currently all my money is in FDs. I want to diversify into equity, gold, and maybe real estate. What's the ideal allocation for a 35-year-old?", "source": "r/IndiaInvestments", "author": "u/diversify_me"},
    {"title": "Best cashback credit card for online shopping", "text": "I do a lot of Amazon and Flipkart shopping. Which credit card gives the best cashback for online purchases? I've seen Amazon Pay ICICI card mentioned a lot — is it really that good?", "source": "r/CreditCardsIndia", "author": "u/online_shopper"},
]

YOUTUBE_POSTS = [
    {"title": "Re: Best Mutual Funds for 2024", "text": "I've been investing in index funds for 2 years now but my returns are below expectations. Should I switch to actively managed funds? My SIP is 10k per month. Would love some advice from experienced investors.", "source": "CA Rachana Ranade", "author": "InvestorRaj2024"},
    {"title": "Re: Complete Guide to Home Loans", "text": "Great video! But you didn't mention processing fees and hidden charges. My bank charged me 0.5% processing fee which was a shock. How do I negotiate better terms on a home loan?", "source": "Finance With Sharan", "author": "HomeBuyerMumbai"},
    {"title": "Re: Credit Card Hacks India", "text": "I'm a student and just got my first credit card. What's the best way to build credit score? Should I use the full limit or keep utilization below 30%? Also, is it true that multiple cards help?", "source": "Akshat Shrivastava", "author": "StudentFinance101"},
    {"title": "Re: Tax Saving Tips for Salaried", "text": "I'm in the 30% tax bracket and currently only saving via EPF. What other options do I have? I've heard about NPS, ELSS, and health insurance premiums. How do I optimize my tax saving?", "source": "Labour Law Advisor", "author": "TaxPayerIndia"},
    {"title": "Re: SIP vs Lump Sum Investment", "text": "I got a 3L bonus this year. Should I invest it all at once in a mutual fund or spread it over 6 months via STP? The market seems overvalued right now. What would you suggest?", "source": "freefincal", "author": "BonusInvestor"},
    {"title": "Re: Health Insurance Explained", "text": "Do I really need a super top-up plan if I already have a 5L base policy from my employer? What happens if I switch jobs? Is personal health insurance necessary if my company provides it?", "source": "Yadnya Investment Academy", "author": "HealthConfused"},
    {"title": "Re: Best Fixed Deposit Rates 2024", "text": "Are bank FDs still worth it with mutual funds giving better returns? I have 10L sitting idle. My risk appetite is very low. What's the best FD rate currently and which bank offers it?", "source": "CA Rachana Ranade", "author": "ConservativeInvestor"},
    {"title": "Re: Personal Loan Guide", "text": "I need a personal loan of 3L for home renovation. The interest rates seem very high at 12-14%. Is there any way to get a lower rate? Should I use my credit card EMI instead?", "source": "Finance With Sharan", "author": "RenovationBudget"},
]

X_POSTS = [
    {"title": "Tweet by @FinanceGuru_IN", "text": "Just started my SIP journey with ₹5000/month in a flexi cap fund. Hope to build a decent corpus in 10 years. Any tips for a beginner? #MutualFunds #SIP #Investing", "source": "@FinanceGuru_IN", "author": "@FinanceGuru_IN"},
    {"title": "Tweet by @MumbaiInvestor", "text": "Home loan EMI is killing me at 8.75% 😭 Anyone know if rates are expected to come down? Should I refinance with another bank? #HomeLoan #InterestRates", "source": "@MumbaiInvestor", "author": "@MumbaiInvestor"},
    {"title": "Tweet by @CreditCardQueen", "text": "Just got approved for a premium credit card with airport lounge access! The annual fee is ₹5000 but the benefits are worth 3x that. #CreditCard #Rewards", "source": "@CreditCardQueen", "author": "@CreditCardQueen"},
    {"title": "Tweet by @TaxSavingTips", "text": "Don't forget: You can save up to ₹46,800 in taxes by investing ₹1.5L in ELSS + ₹50K in NPS under 80CCD(1B). Last date is March 31! #TaxSaving #ELSS #NPS", "source": "@TaxSavingTips", "author": "@TaxSavingTips"},
    {"title": "Tweet by @HealthyWealthy", "text": "Medical emergency wiped out my savings 😞 Don't be like me — get health insurance NOW. Even a basic 5L cover is better than nothing. #HealthInsurance #FinancialPlanning", "source": "@HealthyWealthy", "author": "@HealthyWealthy"},
    {"title": "Tweet by @RetireEarly_IN", "text": "If you invest ₹15,000/month via SIP from age 25, you'll have ₹3.5 Cr by 55 (assuming 12% returns). Start early! #FIRE #RetireEarly #SIP", "source": "@RetireEarly_IN", "author": "@RetireEarly_IN"},
    {"title": "Tweet by @DebtFreeLiving", "text": "Finally paid off my personal loan! It took 3 years of discipline. If you're considering a personal loan, think twice — the interest is brutal at 14%. #DebtFree #PersonalLoan", "source": "@DebtFreeLiving", "author": "@DebtFreeLiving"},
    {"title": "Tweet by @FDvsEquity", "text": "My FD matured at 6.5% while my ELSS gave 22% in the same period. Still think FDs are safe? The real risk is losing to inflation. #FixedDeposit #ELSS #Investing", "source": "@FDvsEquity", "author": "@FDvsEquity"},
]

QUORA_POSTS = [
    {"title": "What are the best mutual funds to invest in India?", "text": "What are the best mutual funds to invest in India?", "source": "Quora", "author": "quora_user"},
    {"title": "Which is better — SIP or lump sum investment?", "text": "Which is better — SIP or lump sum investment?", "source": "Quora", "author": "quora_user"},
    {"title": "How do I choose the right health insurance plan?", "text": "How do I choose the right health insurance plan?", "source": "Quora", "author": "quora_user"},
    {"title": "Is NPS a good investment option for tax saving?", "text": "Is NPS a good investment option for tax saving?", "source": "Quora", "author": "quora_user"},
    {"title": "What is the best credit card in India for cashback?", "text": "What is the best credit card in India for cashback?", "source": "Quora", "author": "quora_user"},
    {"title": "Should I take a home loan or continue paying rent?", "text": "Should I take a home loan or continue paying rent?", "source": "Quora", "author": "quora_user"},
    {"title": "What are the best tax saving options under Section 80C?", "text": "What are the best tax saving options under Section 80C?", "source": "Quora", "author": "quora_user"},
    {"title": "How much term insurance cover do I need?", "text": "How much term insurance cover do I need?", "source": "Quora", "author": "quora_user"},
]

# ── AI-Generated Draft Responses ─────────────────────────────────

DRAFT_RESPONSES = {
    "mutual_fund": "Great question! For beginners, starting with a diversified flexi-cap fund through SIP is an excellent choice. BCI Bluechip Fund has consistently delivered 14-16% CAGR over the last 5 years with relatively lower volatility compared to mid-cap funds. For your risk profile, I'd suggest: 1) BCI Bluechip Fund for stability, 2) BCI Flexi Cap Fund for growth, and 3) BCI Tax Saver ELSS if you need tax benefits under 80C. Start with ₹5,000/month and increase by 10% annually.",
    "home_loan": "This is a common dilemma! BCI Home Loans currently offer rates starting at 8.35% p.a. with flexible repayment options up to 30 years. Key factors to consider: 1) Compare the total cost of renting vs. buying over 10 years, 2) Check if the EMI is within 40% of your take-home salary, 3) Factor in property appreciation in your city. BCI also offers balance transfer facility if you find better rates later. Pro tip: Choose a shorter tenure to save significantly on interest.",
    "credit_card": "For your spending pattern of ₹50k/month, BCI Credit Card Platinum would be ideal! You'd earn: 1) 5% cashback on online shopping (up to ₹500/month), 2) 2% on dining and fuel, 3) Complimentary airport lounge access (4 visits/quarter), 4) Annual fee of ₹2,999 (waived on ₹3L annual spend). The reward points can be redeemed for flights and hotel stays. Based on your spending, you'd earn ₹8,000-10,000 in annual rewards — a net positive even with the fee!",
    "tax_saving": "Smart thinking on maximizing tax benefits! BCI Tax Saver ELSS is one of the top-performing funds in its category with 18.5% CAGR over 5 years. Here's an optimal tax-saving strategy: 1) ₹1.5L in BCI Tax Saver ELSS (80C — 3-year lock-in vs PPF's 15 years), 2) ₹50K in NPS under 80CCD(1B) for additional ₹15,600 tax saving, 3) ₹25K in health insurance premium (80D). Total tax saved: ~₹78,000 annually in the 30% bracket!",
    "health_insurance": "Health insurance is crucial, especially for parents above 60. BCI Health Shield offers comprehensive coverage: 1) ₹10L sum insured for senior citizens, 2) No medical test required up to ₹5L cover, 3) 14,000+ cashless hospitals, 4) Day-1 coverage for accidents. Premium for a 62-year-old would be approximately ₹18,000/year for ₹5L cover. I'd recommend a base plan of ₹5L + a super top-up of ₹20L for complete peace of mind.",
    "sip": "Starting SIP at 28 with ₹5,000/month is a great decision! Based on your 10-year horizon and moderate risk appetite, I'd recommend BCI Flexi Cap Fund — it invests across large, mid, and small caps, giving you diversification in a single fund. Historical returns: 15.2% CAGR over 10 years. At ₹5,000/month with 14% average returns, you could build a corpus of ₹13.5L in 10 years. Consider increasing SIP by 10% annually — that would push the corpus to ₹19L!",
    "term_insurance": "For a 30-year-old earning ₹15L/year with a family, I'd recommend a term cover of ₹1.5-2 Cr (roughly 10-15x annual income). BCI Term Shield offers: 1) ₹1 Cr cover at just ₹8,400/year (pure term, no frills), 2) Claim settlement ratio of 98.2%, 3) Option to add critical illness rider for ₹1,200 extra/year. Key tip: Don't mix insurance with investment — pure term plans give maximum coverage at minimum cost.",
    "fixed_deposit": "While FDs offer safety, the real returns after tax and inflation are often negative! BCI Fixed Deposit offers competitive rates: 1) 7.25% for 1-year FD, 2) 7.5% for senior citizens, 3) Tax-saving FD at 7.1% (5-year lock-in under 80C). However, for your emergency fund, I'd suggest BCI Liquid Fund instead — similar safety, slightly better returns (7.4% pre-tax), and instant redemption up to ₹50K. Best of both worlds!",
    "personal_loan": "For home renovation, a personal loan at 12-14% can be expensive. Consider these BCI alternatives: 1) BCI Home Renovation Loan — secured against property at 9.5% (much cheaper!), 2) BCI Personal Loan — 10.99% for existing BCI account holders, 3) BCI Credit Card EMI — 0% interest for 3-6 months on select categories. If you have a good CIBIL score (750+), you can negotiate the rate down by 1-2%. Always compare total cost including processing fees!",
}

BCI_SCHEMES = [
    "BCI Bluechip Fund", "BCI Flexi Cap Fund", "BCI Tax Saver ELSS",
    "BCI Home Loan", "BCI Credit Card Platinum", "BCI Health Shield",
    "BCI Term Shield", "BCI Fixed Deposit", "BCI Liquid Fund",
    "BCI Personal Loan", "BCI NPS Tier-1",
]

RESPONSE_KEYS = list(DRAFT_RESPONSES.keys())


def seed():
    """Populate the database with realistic demo data."""
    init_db()
    db = SessionLocal()

    # Check if already seeded
    existing = db.query(IngestedPost).count()
    if existing > 0:
        print(f"⚠️  Database already has {existing} posts. Skipping seed.")
        print("   To re-seed, delete data/leadgen.db first.")
        db.close()
        return

    print("🌱 Seeding database with demo data...\n")

    all_posts_data = [
        ("reddit", REDDIT_POSTS),
        ("youtube", YOUTUBE_POSTS),
        ("x", X_POSTS),
        ("quora", QUORA_POSTS),
    ]

    post_objects = []
    now = datetime.now(timezone.utc)

    for platform, posts in all_posts_data:
        for i, p in enumerate(posts):
            post = IngestedPost(
                platform=platform,
                post_id=f"{platform}_{i}_{randint(10000, 99999)}",
                author=p["author"],
                source=p["source"],
                url=f"https://{'www.reddit.com/r/IndiaInvestments/comments/abc' if platform == 'reddit' else 'www.youtube.com/watch?v=xyz' if platform == 'youtube' else 'x.com/user/status/123' if platform == 'x' else 'www.quora.com/What-is'}{randint(100, 999)}",
                title=p["title"],
                text=p["text"],
                timestamp=now - timedelta(hours=randint(1, 72)),
                fetched_at=now - timedelta(hours=randint(0, 24)),
                tier1_passed=True,
                tier2_score=randint(78, 98),
                tier2_passed=True,
            )
            db.add(post)
            post_objects.append(post)

    db.flush()  # Get IDs assigned
    print(f"   ✅ Created {len(post_objects)} ingested posts")

    # Create draft comments for most posts
    statuses = ["pending"] * 15 + ["posted"] * 8 + ["rejected"] * 4 + ["queued"] * 3
    draft_count = 0

    for i, post in enumerate(post_objects):
        if i >= len(statuses):
            break

        response_key = choice(RESPONSE_KEYS)
        status = statuses[i]

        draft = DraftComment(
            post_id=post.id,
            matched_scheme=choice(BCI_SCHEMES),
            intent_score=post.tier2_score,
            scheme_relevance=round(0.72 + (randint(0, 25) / 100), 2),
            draft_text=DRAFT_RESPONSES[response_key],
            status=status,
            created_at=now - timedelta(hours=randint(0, 12)),
            posted_at=(now - timedelta(hours=randint(0, 6))) if status == "posted" else None,
        )
        db.add(draft)
        draft_count += 1

    print(f"   ✅ Created {draft_count} draft comments")

    # Create pipeline run records
    for platform in ["reddit", "youtube", "x", "quora"]:
        run = PipelineRun(
            platform=platform,
            started_at=now - timedelta(minutes=randint(5, 120)),
            completed_at=now - timedelta(minutes=randint(1, 4)),
            posts_fetched=len([p for p in post_objects if p.platform == platform]),
            posts_filtered=len([p for p in post_objects if p.platform == platform]) - randint(0, 3),
            drafts_generated=len([p for p in post_objects if p.platform == platform]) - randint(1, 4),
            status="completed",
        )
        db.add(run)

    print(f"   ✅ Created 4 pipeline run records")

    db.commit()
    db.close()

    print(f"\n🎉 Seed complete! {len(post_objects)} posts + {draft_count} drafts loaded.")
    print("   Run the server with: uvicorn api.server:app --reload")


if __name__ == "__main__":
    seed()
