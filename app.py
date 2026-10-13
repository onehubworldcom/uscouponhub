import csv, os, re, sqlite3, hashlib, base64, json, time
from urllib import request as urlrequest, parse as urlparse, error as urlerror
from affiliate import get_match, get_networks, build_destination, log_click
from datetime import datetime
from flask import Flask, render_template, abort, Response, request, url_for, redirect
from seo_eligibility import (RESERVED_SLUGS, STORE_INDEXABLE_WHERE,
                             CURRENT_OFFER_WHERE, store_sitemap_where)

BASE=os.path.dirname(os.path.abspath(__file__))
DB=os.environ.get('DATABASE_PATH', os.path.join(BASE,'data','uscouponhub.db'))
DEFAULT_CSV=os.path.join(BASE,'data','Stores_Final.csv')
if not os.path.exists(DEFAULT_CSV):
    # The project ZIP stores the CSV in the project root, so support both
    # layouts and avoid a fresh deployment starting with an empty database.
    DEFAULT_CSV=os.path.join(BASE,'Stores_Final.csv')
CSV_FILE=os.environ.get('STORES_CSV', DEFAULT_CSV)
app=Flask(__name__)
@app.template_filter('format_number')
def format_number(value):
    try:
        return f"{int(value):,}"
    except (ValueError, TypeError):
        return value

@app.template_filter('store_meta_description')
def store_meta_description(value):
    name=(value or 'Store').strip()
    variants=[
        f'Find {name} Promo Codes, Coupon Codes, Discounts, Sale Offers, Black Friday Deals and Up to 90% OFF where available. Compare current Store Deals and Offers.',
        f'Find {name} Promo Codes, Coupon Codes, Discounts, Sale Offers and Black Friday Deals. Up to 90% OFF where available. Check Store Deals before checkout.',
        f'{name}: Promo Codes, Coupon Codes, Discounts, Sale Offers, Black Friday Deals and Up to 90% OFF where available. Compare current Store Deals.',
        f'{name}: Coupon Codes, Promo Codes, Discounts, Sale Offers, Black Friday Deals and Up to 90% OFF where available. Check current Store Deals.',
        f'{name}: Coupon Codes, Promo Codes, Discounts, Sale Offers, Black Friday Deals, Up to 90% OFF where available. Check Store Deals.',
    ]
    for description in variants:
        if 150 <= len(description) <= 160:
            return description
    # Extremely long Store names are shortened only inside the Meta Description.
    # The full Store name remains unchanged everywhere else on the page.
    short_name=name if len(name) <= 38 else name[:37].rstrip() + '…'
    return f'{short_name}: Coupon Codes, Promo Codes, Discounts, Sale Offers, Black Friday Deals, Up to 90% OFF where available. Check Store Deals.'
@app.template_filter('content_meta_description')
def content_meta_description(value):
    text=re.sub(r'\s+',' ',(value or 'Practical shopping guidance from US Coupon Hub.').strip())
    additions=[
        ' Compare prices, Offer terms, delivery and returns before checkout.',
        ' Review current Store details and shopping terms before checkout.',
        ' Use this practical US Coupon Hub guide before you buy.'
    ]
    candidate=text
    for extra in additions:
        if len(candidate) >= 150:
            break
        candidate += extra
    if len(candidate) > 160:
        cut=candidate.rfind(' ',0,158)
        candidate=(candidate[:cut if cut >= 150 else 157].rstrip(' ,;:-') + '.')
    if len(candidate) < 150:
        candidate=(candidate + ' Shop smarter with US Coupon Hub.').strip()
    if len(candidate) > 160:
        cut=candidate.rfind(' ',0,158)
        candidate=(candidate[:cut if cut >= 150 else 157].rstrip(' ,;:-') + '.')
    return candidate


STATES={'california':'California','texas':'Texas','florida':'Florida','new-york':'New York','illinois':'Illinois','pennsylvania':'Pennsylvania','ohio':'Ohio','georgia':'Georgia','north-carolina':'North Carolina','michigan':'Michigan'}
CITIES={'new-york':'New York, NY','los-angeles':'Los Angeles, CA','chicago':'Chicago, IL','houston':'Houston, TX','phoenix':'Phoenix, AZ','philadelphia':'Philadelphia, PA','san-antonio':'San Antonio, TX','san-diego':'San Diego, CA','dallas':'Dallas, TX','san-jose':'San Jose, CA'}
CATEGORIES=['shopping','fashion','electronics','beauty','home-garden','travel','food-drink','software','baby-kids']
SEASONAL_EVENTS={'halloween':'Halloween','black-friday':'Black Friday','cyber-monday':'Cyber Monday'}
RESERVED=RESERVED_SLUGS
CURATED_STORE_INDEXING_ENABLED=os.environ.get('CURATED_STORE_INDEXING_ENABLED','0').strip().lower() in {'1','true','yes','on'}


CATEGORY_CONFIG={
    'shopping': {'label':'Shopping','aliases':['shopping','deals','stores'], 'query':'shopping deals', 'subcategories':['Department Stores','Deals','Gift Cards']},
    'fashion': {'label':'Fashion','aliases':['fashion','clothes','clothing','apparel','shoes'], 'query':'fashion clothing shoes', 'subcategories':['Women’s Fashion','Men’s Fashion','Shoes','Accessories']},
    'electronics': {'label':'Electronics','aliases':['electronics','tech','technology','gadgets'], 'query':'electronics', 'subcategories':['Phones & Tablets','Laptops & Computers','TV & Home Theater','Gaming','Cameras']},
    'beauty': {'label':'Beauty','aliases':['beauty','makeup','skincare','skin care','cosmetics'], 'query':'beauty skincare makeup', 'subcategories':['Makeup','Skin Care','Hair Care','Fragrance']},
    'home-garden': {'label':'Home & Garden','aliases':['home','garden','furniture','home decor'], 'query':'home garden', 'subcategories':['Furniture','Home Decor','Kitchen','Garden']},
    'travel': {'label':'Travel','aliases':['travel','hotel','hotels','flights'], 'query':'travel accessories', 'subcategories':['Hotels','Flights','Luggage','Travel Accessories']},
    'food-drink': {'label':'Food & Drink','aliases':['food','drink','groceries','grocery'], 'query':'food kitchen', 'subcategories':['Groceries','Restaurants','Coffee & Tea','Kitchen']},
    'software': {'label':'Software','aliases':['software','apps','app','digital'], 'query':'software', 'subcategories':['Security','Productivity','Creative','Business']},
    'baby-kids': {'label':'Baby & Kids','aliases':['baby','kids','children','toys'], 'query':'baby kids', 'subcategories':['Baby Gear','Kids Clothing','Toys','School']},
}

SHOPPING_GUIDES = {
    'save-money-online-shopping': {
        'title': 'Best Online Shopping Tips to Save Money',
        'description': 'Practical ways to compare prices, plan purchases and use legitimate discounts when shopping online.',
        'intro': 'Saving money online is usually about preparation rather than chasing every offer. A simple routine can help you compare options and avoid spending more than planned.',
        'sections': [
            ('Start with a shopping list', 'Write down what you actually need before searching. A list makes it easier to compare similar products and reduces impulse purchases.'),
            ('Compare the final price', 'Look beyond the headline price. Check shipping, taxes, membership requirements and any conditions that change the final amount you pay.'),
            ('Check coupons carefully', 'Read the terms of a promo code before relying on it. Some codes apply only to selected products, new customers or a minimum order value.'),
            ('Time larger purchases', 'For non-urgent purchases, compare prices around major seasonal sales. Do not assume every advertised sale is automatically the lowest available price.'),
            ('Keep your budget in control', 'Set a spending limit before browsing. A discount is useful only when the purchase itself fits your needs and budget.')],
        'tips': ['Compare at least two trustworthy sellers when possible.', 'Keep a note of prices for larger planned purchases.', 'Avoid entering payment details on unfamiliar or suspicious websites.']},
    'find-legit-promo-codes': {
        'title': 'How to Find Legit Promo Codes',
        'description': 'A practical guide to checking promo codes and avoiding expired or misleading offers.',
        'intro': 'Promo codes can reduce the cost of an order, but not every code found online is active or relevant. A careful checking process helps you focus on offers that are clear and useful.',
        'sections': [('Check the source', 'Start with the merchant website, its official emails or reputable deal resources. Be cautious when a page makes unrealistic promises.'), ('Read the conditions', 'Check the expiry date, minimum spend, product exclusions and whether the code is limited to specific customers.'), ('Test one code at a time', 'Apply codes individually at checkout so you can see exactly which discount is accepted and how it changes the total.'), ('Do not share unnecessary information', 'A coupon should not require you to provide sensitive information that is unrelated to the purchase.'), ('Report incorrect listings', 'If you find an expired or misleading code, report it to the website that listed it when a reporting option is available.')],
        'tips': ['Treat unusually large discount claims with extra caution.', 'Check whether an offer changes the final checkout price.', 'Keep screenshots or order records for important promotions.']},
    'black-friday-shopping-guide': {
        'title': 'Complete Black Friday Shopping Guide',
        'description': 'Plan a focused Black Friday shopping strategy with budgets, price checks and safe checkout habits.',
        'intro': 'Black Friday can bring a large number of promotions in a short period. Planning ahead helps you decide what matters and avoid rushed purchases.',
        'sections': [('Make a priority list', 'Separate must-have items from nice-to-have purchases and assign a maximum budget to each category.'), ('Research before the event', 'Learn the normal price range of important items before sale season so you have context for advertised discounts.'), ('Check retailer terms', 'Review return policies, shipping deadlines and any limits attached to sale items.'), ('Compare alternatives', 'If one product sells out, compare similar options rather than immediately buying an unrelated item.'), ('Protect your accounts', 'Use strong, unique passwords and shop through trusted websites and official retailer apps.')],
        'tips': ['Keep your budget visible while shopping.', 'Do not buy only because a countdown creates pressure.', 'Save order confirmations and delivery information.']},
    'cyber-monday-shopping-guide': {
        'title': 'Cyber Monday Shopping Guide',
        'description': 'How to prepare for online-focused Cyber Monday promotions and shop with a clear plan.',
        'intro': 'Cyber Monday is centered on online shopping, which makes comparison easier but also increases the number of offers competing for attention.',
        'sections': [('Prepare accounts in advance', 'For trusted stores you already use, update your delivery information before a busy shopping period.'), ('Compare product details', 'Check model numbers, sizes, versions and included accessories before comparing prices.'), ('Watch total cost', 'Free shipping thresholds and delivery fees can change which offer is actually better.'), ('Use trusted payment methods', 'Prefer familiar checkout systems and verify that you are on the correct website before paying.'), ('Review the order immediately', 'After checkout, confirm the item, quantity, shipping address and final amount in your order confirmation.')],
        'tips': ['Do not reuse passwords across shopping accounts.', 'Read product descriptions instead of relying only on images.', 'Be cautious with unfamiliar sites offering unrealistic prices.']},
    'holiday-shopping-calendar': {
        'title': 'Holiday Shopping Calendar and Planning Guide',
        'description': 'A simple planning framework for major seasonal shopping periods throughout the year.',
        'intro': 'A shopping calendar is useful because different needs appear at different times of the year. Planning ahead can reduce last-minute pressure and help you set realistic budgets.',
        'sections': [('List important dates', 'Note birthdays, school needs, travel plans and major holidays that may require purchases.'), ('Plan seasonal categories', 'Think ahead about gifts, clothing, home items and event supplies instead of buying everything at the last minute.'), ('Set monthly limits', 'Divide expected spending across several months when possible.'), ('Track useful price ranges', 'For planned purchases, note typical prices so future offers have context.'), ('Leave room for changes', 'Shipping delays, stock changes and personal needs can shift plans, so avoid spending the entire budget too early.')],
        'tips': ['Use a calendar for planned purchases.', 'Prioritize needs before seasonal extras.', 'Review your plan before each major sale period.']},
    'back-to-school-shopping-guide': {
        'title': 'Back-to-School Shopping Guide',
        'description': 'A practical way to organize school shopping lists, compare essentials and avoid duplicate purchases.',
        'intro': 'Back-to-school shopping is easier when the list is organized by priority. Start with required items and check what is already available at home.',
        'sections': [('Check the official list', 'Use the school or teacher list when available and separate required items from optional preferences.'), ('Inventory supplies at home', 'Check backpacks, stationery and other supplies before buying replacements.'), ('Compare quality and price', 'The cheapest item is not always the best value if it needs to be replaced quickly.'), ('Buy in stages', 'Purchase essentials first and wait on optional items until the actual need is clear.'), ('Keep receipts', 'Receipts help with exchanges when sizes, specifications or requirements change.')],
        'tips': ['Avoid buying duplicate supplies.', 'Check sizing policies for clothing and shoes.', 'Set a category budget before browsing.']},
    'compare-online-deals': {
        'title': 'How to Compare Online Deals',
        'description': 'Compare products, prices, shipping and return terms instead of judging an offer by the discount percentage alone.',
        'intro': 'A good deal is about the complete purchase, not only a large percentage shown in an advertisement.',
        'sections': [('Match the exact product', 'Compare the same model, size, condition and included accessories whenever possible.'), ('Calculate the total', 'Include shipping, taxes and required fees before deciding which option costs less.'), ('Check delivery timing', 'A lower price may not be useful if delivery is too late for your needs.'), ('Read return rules', 'Understand the return window, condition requirements and any restocking or shipping costs.'), ('Consider seller reliability', 'Use established retailers or marketplaces with clear buyer protections.')],
        'tips': ['Create a simple comparison list for expensive purchases.', 'Do not compare different product versions as if they are identical.', 'Keep the final checkout amount as your main comparison number.']},
    'smart-holiday-gift-shopping': {
        'title': 'Smart Holiday Gift Shopping Tips',
        'description': 'Plan thoughtful gifts with a budget, delivery timeline and flexible backup options.',
        'intro': 'Holiday gift shopping can become stressful when every purchase is left until the final days. A small plan makes the process easier and more personal.',
        'sections': [('Make a recipient list', 'List recipients and a rough spending range before searching for products.'), ('Focus on interests', 'Use the recipient’s hobbies and needs instead of choosing only what is heavily promoted.'), ('Order early when possible', 'Extra time provides more flexibility if an item is delayed or needs to be exchanged.'), ('Keep a backup idea', 'Popular items can sell out, so identify one or two alternatives in advance.'), ('Respect your total budget', 'Small gifts add up quickly, so review the total before final checkout.')],
        'tips': ['Track purchases to avoid duplicate gifts.', 'Check return deadlines for gifts.', 'Avoid overspending to match someone else’s budget.']},
    'avoid-expired-coupon-codes': {
        'title': 'How to Avoid Expired Coupon Codes',
        'description': 'A checklist for verifying coupon dates, terms and checkout results before relying on a code.',
        'intro': 'Expired coupon codes are common because promotions change quickly. A short verification checklist can save time and prevent disappointment at checkout.',
        'sections': [('Look for dates', 'Prefer listings that clearly state when an offer was checked or when it expires.'), ('Check exclusions', 'Some codes exclude sale items, specific brands or certain categories.'), ('Confirm account requirements', 'A code may be limited to new customers, members or a particular region.'), ('Apply before payment', 'Verify that the discount appears in the order summary before completing payment.'), ('Do not force a purchase', 'If the code does not work, compare the normal price instead of buying solely because you expected a discount.')],
        'tips': ['Read the exact error message when a code fails.', 'Try only codes that match your order conditions.', 'Remember that some offers are automatically applied and need no code.']},
    'seasonal-shopping-deals-guide': {
        'title': 'Seasonal Shopping Deals Guide',
        'description': 'Use seasonal sales as part of a year-round shopping plan without relying on hype or unnecessary purchases.',
        'intro': 'Seasonal promotions can be useful for planned purchases, but the best approach is to start with a need and then evaluate available offers.',
        'sections': [('Plan around real needs', 'Make a list of purchases you expect in the coming months before major sale periods begin.'), ('Understand the season', 'Different events emphasize different product categories, so compare what is actually relevant to your list.'), ('Check stock and alternatives', 'Have alternatives ready for popular products that may sell out.'), ('Review policies before checkout', 'Seasonal sales can have different return or delivery conditions.'), ('Track results after shopping', 'Review whether the purchases were useful and within budget to improve future planning.')],
        'tips': ['Use seasonal events as opportunities, not obligations.', 'Compare the final price before buying.', 'Keep a record of large purchases for warranty and return purposes.']},

    'check-sale-price-real-deal': {
        'title': 'How to Check If a Sale Price Is Really a Deal',
        'description': 'A practical way to judge sale prices using normal price ranges, product details and the final checkout total.',
        'intro': 'A sale label does not automatically mean the price is unusually low. The safest comparison starts with the exact product, its recent price range and the complete amount you will pay.',
        'sections': [
            ('Match the exact product', 'Check the model number, size, color, condition and included accessories before comparing prices. A similar-looking item may not be the same version.'),
            ('Look for a normal price range', 'Compare the current price with prices from other established sellers and, when possible, with prices you have previously noted for the same product.'),
            ('Ignore the percentage until the price makes sense', 'A large percentage discount can look impressive even when the starting price is unusually high. Focus first on the actual selling price.'),
            ('Calculate the checkout total', 'Add shipping, required fees and any minimum-spend conditions. The best-looking sale can become the more expensive option at checkout.'),
            ('Check whether the timing works for you', 'A lower price is not useful if the delivery date, return policy or product condition does not meet your needs.')],
        'tips': ['Compare the same product version.', 'Use the final checkout total as your main number.', 'Do not buy only because a sale timer creates urgency.']},
    'free-shipping-vs-coupon-discount': {
        'title': 'Free Shipping vs Coupon Discount: Which Saves More?',
        'description': 'Compare shipping charges and coupon discounts using the total amount due rather than the headline promotion.',
        'intro': 'Free shipping and percentage-off coupons can both reduce an order, but the better option depends on the starting price, shipping charge and coupon conditions.',
        'sections': [
            ('Write down the starting total', 'Begin with the cost of the items you already planned to buy. Do not add extra products simply to make an offer look better.'),
            ('Calculate the coupon result', 'Apply the coupon to eligible items and note the discounted subtotal. Check whether any exclusions or minimum-spend rules change the result.'),
            ('Add shipping to the coupon option', 'A strong coupon can still be less useful if the order carries a high delivery charge.'),
            ('Calculate the free-shipping option separately', 'Compare the same basket with free shipping and no coupon when the retailer does not allow promotions to be combined.'),
            ('Choose the lower final total', 'The promotion with the smaller advertised benefit can still produce the lower checkout price.')],
        'tips': ['Compare both options with the same basket.', 'Check whether promotions can be combined.', 'Do not add unnecessary items only to reach a free-shipping threshold.']},
    'online-return-policy-checklist': {
        'title': 'Online Return Policy Checklist Before You Buy',
        'description': 'Check return windows, return shipping, final-sale rules and refund methods before placing an online order.',
        'intro': 'A low price can lose its value if an item is difficult or expensive to return. Reading the return policy before checkout can prevent avoidable costs later.',
        'sections': [
            ('Check the return window', 'Find out how many days you have to start a return and whether the clock begins at purchase, shipment or delivery.'),
            ('Look for final-sale exclusions', 'Clearance items, personalized products, opened electronics and other categories may have different rules or may not be returnable.'),
            ('Check who pays return shipping', 'Some retailers provide prepaid returns while others deduct shipping or handling charges from the refund.'),
            ('Confirm the refund method', 'A return may go back to the original payment method, store credit or an exchange depending on the policy and item type.'),
            ('Keep packaging and records when needed', 'For higher-value purchases, save the order confirmation and any packaging required by the seller until you know the item is suitable.')],
        'tips': ['Read return rules before buying expensive items.', 'Check whether sale items have different conditions.', 'Keep order records until the return period ends.']},
    'safe-online-shopping-checklist': {
        'title': 'Safe Online Shopping Checklist',
        'description': 'Simple checks for website identity, checkout security, payment methods and order records before buying online.',
        'intro': 'Online shopping is easier when you use a short safety routine. The goal is to confirm that you are dealing with the intended retailer and that the checkout process looks legitimate.',
        'sections': [
            ('Verify the website address', 'Check the domain name carefully before entering account or payment information, especially when you arrived from an ad, message or unfamiliar link.'),
            ('Use trusted checkout methods', 'Prefer payment methods and checkout systems you recognize, and avoid sending payment through unusual methods requested outside the normal checkout flow.'),
            ('Be cautious with unrealistic prices', 'An unusually low price on an unfamiliar website is a reason to check the seller, policies and contact information more carefully.'),
            ('Protect shopping accounts', 'Use strong, unique passwords and enable additional account security features when a retailer provides them.'),
            ('Save your confirmation', 'Keep the order confirmation, seller name, total paid and delivery information until the purchase is completed satisfactorily.')],
        'tips': ['Type a retailer address directly when in doubt.', 'Do not share unnecessary personal information for a coupon.', 'Keep order confirmations for important purchases.']},
    'holiday-shipping-deadlines-guide': {
        'title': 'How to Plan Holiday Shipping and Delivery Deadlines',
        'description': 'Plan holiday purchases around delivery estimates, seller processing times and backup options.',
        'intro': 'Holiday shopping is not only about finding a price. Delivery timing becomes part of the decision when an item is needed for a specific date.',
        'sections': [
            ('Start with the date you actually need the item', 'Work backward from the event or holiday instead of relying only on a retailer headline such as arrives before the holidays.'),
            ('Include seller processing time', 'Some orders need time to be prepared before the carrier receives the package, especially personalized or marketplace items.'),
            ('Review the delivery estimate at checkout', 'The product page estimate can change after you enter your address or select a shipping method.'),
            ('Leave a buffer for important gifts', 'Weather, inventory changes and carrier delays can happen, so avoid choosing the last possible delivery date when timing matters.'),
            ('Prepare a backup option', 'For time-sensitive purchases, identify a local pickup or alternative product in case shipping changes unexpectedly.')],
        'tips': ['Check the final delivery estimate before paying.', 'Order time-sensitive items earlier when possible.', 'Keep tracking and order information together.']},
}


BLOG_POSTS = {
    'how-to-plan-weekly-shopping-budget': {
        'title': 'How to Plan a Weekly Shopping Budget',
        'description': 'A simple weekly shopping budget routine to help organize purchases, compare prices and avoid unnecessary spending.',
        'date': '2026-08-29',
        'category': 'Budgeting',
        'read_time': '5 min read',
        'icon': '🧾',
        'intro': 'A weekly shopping budget gives you a clear limit before browsing. The goal is not to remove every extra purchase, but to make planned choices and understand the total cost.',
        'sections': [('Start with essentials', 'List groceries and household items you actually need before opening shopping apps or visiting stores.'), ('Set one total limit', 'Choose a realistic weekly amount and keep the total visible while comparing products and shipping costs.'), ('Separate planned and optional purchases', 'Mark items that can wait so promotions do not automatically become purchases.'), ('Compare the final price', 'Check shipping, taxes, membership conditions and bundle requirements before deciding which option is actually cheaper.'), ('Review at the end of the week', 'Look back at what you bought and what was left over. A short review can improve next week’s list.')],
        'tips': ['Make the list before browsing deals.', 'Use a weekly total instead of chasing every individual discount.', 'Keep receipts for larger purchases and returns.']
    },
    'how-to-compare-online-prices': {
        'title': 'How to Compare Online Prices Before You Buy',
        'description': 'A practical method for comparing products, shipping costs and seller terms before making an online purchase.',
        'date': '2026-08-28', 'category': 'Smart Shopping', 'read_time': '6 min read', 'icon': '🔎',
        'intro': 'A lower sticker price does not always mean a lower final cost. Comparing the same product carefully can help you make a clearer decision.',
        'sections': [('Match the exact product', 'Check model numbers, sizes, colors and included accessories so you are comparing like with like.'), ('Calculate the total cost', 'Include shipping, taxes and required membership fees when reviewing offers.'), ('Check delivery timing', 'A cheaper option may not be useful if the delivery date does not meet your needs.'), ('Read return information', 'Before buying, review the return window and any conditions that apply to the item.'), ('Save your comparison', 'For larger purchases, keep a short note of the options so you can avoid repeatedly starting from scratch.')],
        'tips': ['Compare total cost, not just sticker price.', 'Check exact product specifications.', 'Keep important order records.']
    },

    'why-20-percent-coupon-can-cost-more-than-free-shipping': {
        'title': 'Why a 20% Coupon Can Cost More Than Free Shipping',
        'description': 'A simple example of why shoppers should compare the final checkout total instead of the biggest-looking promotion.',
        'date': '2026-10-11', 'category': 'Smart Shopping', 'read_time': '5 min read', 'icon': '🧮',
        'intro': 'A percentage-off coupon often looks more valuable than free shipping, but that is not always true. The only reliable comparison is the amount you will actually pay for the same basket.',
        'sections': [('Start with the same basket', 'Compare promotions using identical items so the result is meaningful.'), ('Calculate the percentage discount', 'Work out the eligible discount and check whether excluded items or a maximum discount limit apply.'), ('Add delivery charges', 'If the coupon option still has shipping, include that charge before comparing it with free shipping.'), ('Check minimum-spend rules', 'A promotion that requires extra purchases can increase total spending even when it creates a discount.'), ('Use the final total', 'Choose based on the complete checkout amount and your actual need for the items, not the size of the promotional headline.')],
        'tips': ['Use the same basket for every comparison.', 'Include shipping before deciding.', 'Do not spend extra only to unlock a promotion.'],
        'related_guide_slug': 'free-shipping-vs-coupon-discount',
        'related_guide_title': 'Free Shipping vs Coupon Discount: Which Saves More?'
    },
    'coupon-code-not-working-things-to-check': {
        'title': 'Coupon Code Not Working? 7 Things to Check',
        'description': 'Common reasons a coupon is rejected, including expiry dates, minimum spends, exclusions and customer eligibility.',
        'date': '2026-10-11', 'category': 'Promo Codes', 'read_time': '6 min read', 'icon': '🏷️',
        'intro': 'A rejected coupon does not always mean the code was fake. Retailers often attach conditions that determine when and where a promotion can be used.',
        'sections': [('Check the expiry date', 'The promotion may have ended or may only work during a specified time period.'), ('Check the minimum spend', 'Some coupons only activate after the eligible subtotal reaches a required amount.'), ('Review product exclusions', 'Certain brands, sale items, gift cards or categories may not qualify.'), ('Check customer eligibility', 'The offer may be for new customers, members, app users or a specific region.'), ('Look for automatic discounts', 'A store may already be applying another promotion that cannot be combined with the coupon.'), ('Check spelling and spacing', 'Enter the code exactly as provided and remove accidental spaces before or after it.'), ('Read the checkout message', 'The retailer error message often explains whether the problem is expiry, eligibility or the contents of the cart.')],
        'tips': ['Do not keep trying unrelated codes at random.', 'Read the retailer terms when available.', 'Confirm any accepted discount in the order summary.'],
        'related_guide_slug': 'find-legit-promo-codes',
        'related_guide_title': 'How to Find Legit Promo Codes'
    },
    'percentage-off-vs-dollar-off': {
        'title': 'Percentage Off vs Dollar Off: How to Compare Them',
        'description': 'Compare percentage and fixed-dollar discounts by calculating what each promotion does to the same eligible order.',
        'date': '2026-10-11', 'category': 'Savings Math', 'read_time': '5 min read', 'icon': '💵',
        'intro': 'A 15% discount and a $20 discount cannot be compared by appearance alone. The better promotion depends on the eligible order value and any limits attached to the offer.',
        'sections': [('Use the eligible subtotal', 'Start with the amount that actually qualifies for the promotion.'), ('Calculate the percentage option', 'Multiply the eligible subtotal by the percentage and check whether the retailer sets a maximum discount.'), ('Calculate the fixed-dollar option', 'Subtract the fixed amount, making sure the order meets any minimum-spend requirement.'), ('Add other costs', 'Shipping and fees can change the better choice even after the discount is calculated.'), ('Check whether you needed the full basket', 'Do not increase an order only to cross a threshold unless the added products were already planned purchases.')],
        'tips': ['Calculate both discounts on the same eligible subtotal.', 'Check maximum-discount limits.', 'Compare the final checkout amount.'],
        'related_guide_slug': 'compare-online-deals',
        'related_guide_title': 'How to Compare Online Deals'
    },
    'return-shipping-can-change-deal': {
        'title': 'How Return Shipping Can Change the Real Cost of a Deal',
        'description': 'Why return shipping, restocking rules and refund methods belong in your price comparison for higher-value purchases.',
        'date': '2026-10-11', 'category': 'Buyer Planning', 'read_time': '5 min read', 'icon': '📦',
        'intro': 'Two retailers can sell the same item at similar prices while offering very different return terms. Those differences matter most when size, fit or product compatibility is uncertain.',
        'sections': [('Check return shipping', 'A prepaid return can be more convenient than paying to ship a large or heavy item back.'), ('Look for restocking charges', 'Some categories may have fees or special conditions that reduce the refund.'), ('Check the refund method', 'Store credit may be less flexible than a refund to the original payment method.'), ('Compare the return window', 'A longer window can be useful for gifts or products that need time to evaluate.'), ('Balance price and flexibility', 'A slightly higher purchase price can sometimes be worthwhile when the return policy materially reduces your risk and potential cost.')],
        'tips': ['Read the return policy before buying.', 'Pay extra attention to large or hard-to-fit items.', 'Keep packaging until you know the product works for you.'],
        'related_guide_slug': 'online-return-policy-checklist',
        'related_guide_title': 'Online Return Policy Checklist Before You Buy'
    },
    'simple-price-tracking-before-major-sales': {
        'title': 'Simple Price Tracking Before Black Friday and Holiday Sales',
        'description': 'Create a basic price record before major sales so you can judge promotions with more context.',
        'date': '2026-10-11', 'category': 'Seasonal Planning', 'read_time': '6 min read', 'icon': '📈',
        'intro': 'You do not need a complicated system to understand whether a major sale price looks useful. A short record of the products you actually plan to buy can give you helpful context.',
        'sections': [('Choose only planned products', 'Track items you genuinely expect to purchase rather than collecting dozens of random sale targets.'), ('Record the exact model', 'Save the model number, size or version so later comparisons are like for like.'), ('Note the current price', 'Write down the price from one or two established sellers before the sale period starts.'), ('Record shipping and bundle details', 'A price comparison is more useful when you also know whether shipping or accessories are included.'), ('Compare sale-day totals', 'When the event begins, compare the final checkout price with your earlier notes instead of relying only on the advertised percentage.')],
        'tips': ['Track a short list of real purchase targets.', 'Record exact product versions.', 'Compare final prices during the sale.'],
        'related_guide_slug': 'black-friday-shopping-guide',
        'related_guide_title': 'Complete Black Friday Shopping Guide'
    },
}

def category_from_query(value):
    normalized=normalize_search_query(value) if 'normalize_search_query' in globals() else (value or '').strip().lower()
    for slug, cfg in CATEGORY_CONFIG.items():
        if normalized == slug or normalized in cfg['aliases']:
            return slug
    return None

_EBAY_TOKEN = None
_EBAY_TOKEN_EXPIRES_AT = 0
_EBAY_LAST_ERROR = None

def ebay_api_base():
    env = os.environ.get('EBAY_ENV', 'production').strip().lower()
    return 'https://api.sandbox.ebay.com' if env == 'sandbox' else 'https://api.ebay.com'

def ebay_get_application_token():
    global _EBAY_TOKEN, _EBAY_TOKEN_EXPIRES_AT, _EBAY_LAST_ERROR
    now = time.time(); _EBAY_LAST_ERROR = None
    if _EBAY_TOKEN and now < (_EBAY_TOKEN_EXPIRES_AT - 60): return _EBAY_TOKEN
    client_id = os.environ.get('EBAY_CLIENT_ID', '').strip(); client_secret = os.environ.get('EBAY_CLIENT_SECRET', '').strip()
    if not client_id or not client_secret: _EBAY_LAST_ERROR = 'Missing EBAY_CLIENT_ID or EBAY_CLIENT_SECRET.'; return None
    basic = base64.b64encode(f'{client_id}:{client_secret}'.encode('utf-8')).decode('ascii')
    body = urlparse.urlencode({'grant_type': 'client_credentials','scope': 'https://api.ebay.com/oauth/api_scope'}).encode('utf-8')
    req = urlrequest.Request(ebay_api_base() + '/identity/v1/oauth2/token', data=body, headers={'Authorization': 'Basic ' + basic,'Content-Type': 'application/x-www-form-urlencoded','Accept': 'application/json'}, method='POST')
    try:
        with urlrequest.urlopen(req, timeout=15) as response: payload = json.loads(response.read().decode('utf-8'))
    except Exception as exc:
        _EBAY_LAST_ERROR = f'OAuth request failed: {exc}'; return None
    token = payload.get('access_token')
    if not token: _EBAY_LAST_ERROR = 'OAuth response did not contain an access token.'; return None
    _EBAY_TOKEN = token; _EBAY_TOKEN_EXPIRES_AT = now + max(60, int(payload.get('expires_in', 7200))); return token

def ebay_search_items(query, limit=12):
    token = ebay_get_application_token()
    if not token: return None, _EBAY_LAST_ERROR or 'eBay OAuth is not available yet.'
    params = urlparse.urlencode({'q': query,'limit': max(1, min(int(limit), 50))})
    req = urlrequest.Request(ebay_api_base() + '/buy/browse/v1/item_summary/search?' + params, headers={'Authorization': 'Bearer ' + token,'Accept': 'application/json','X-EBAY-C-MARKETPLACE-ID': os.environ.get('EBAY_MARKETPLACE_ID', 'EBAY_US')})
    try:
        with urlrequest.urlopen(req, timeout=15) as response: payload = json.loads(response.read().decode('utf-8'))
    except urlerror.HTTPError as exc: return None, f'eBay search is temporarily unavailable (HTTP {exc.code}).'
    except (urlerror.URLError, ValueError, TimeoutError): return None, 'eBay search is temporarily unavailable.'
    items=[]
    for item in payload.get('itemSummaries', []):
        price=item.get('price') or {}; image=(item.get('image') or {}).get('imageUrl',''); shipping=item.get('shippingOptions') or []; shipping_cost=''
        if shipping and shipping[0].get('shippingCost'):
            sc=shipping[0]['shippingCost'];
            if sc.get('value') not in (None,''): shipping_cost=f"{sc.get('currency','')} {sc.get('value','')}".strip()
        items.append({'title':item.get('title','eBay item'),'price':f"{price.get('currency','')} {price.get('value','')}".strip(),'image':image,'url':item.get('itemWebUrl',''),'condition':item.get('condition',''),'shipping':shipping_cost})
    return items, None

def ebay_items_match_query(items, query):
    generic={'store','stores','shop','shopping','deal','deals','boutique','online'}
    words=[w for w in re.findall(r'[a-z0-9]+', normalize_search_query(query)) if len(w)>=3 and w not in generic and not w.isdigit()]
    if not words: return True
    sample=' '.join((item.get('title') or '').lower() for item in (items or [])[:6])
    return any(word in sample for word in words)

def ebay_search_smart(query, category='', limit=12):
    queries=smart_ebay_queries(query, category)
    if not queries: return [], None, ''
    last_error=None; original_normalized=normalize_search_query(query)
    for index, candidate in enumerate(queries):
        items, error=ebay_search_items(candidate, limit=limit)
        if items:
            if index == 0 and original_normalized not in SMART_EBAY_SEARCH and not ebay_items_match_query(items, candidate) and len(queries)>1: continue
            return items, None, candidate
        if error: last_error=error
    return [], last_error, queries[0]

def amazon_associate_tag(): return os.environ.get('AMAZON_ASSOCIATE_TAG', 'uscouponhub-20').strip()
def amazon_search_url(query):
    q=(query or '').strip(); params={'k':q}; tag=amazon_associate_tag()
    if tag: params['tag']=tag
    return 'https://www.amazon.com/s?' + urlparse.urlencode(params)

def automatic_store_offers(store, existing_offers):
    if existing_offers: return list(existing_offers)
    category=(store['category'] or 'Shopping').replace('-', ' ').title()
    return [{'title':f'Shop current {store["name"]} offers','description':'Automatic savings card. Compare current prices and available promotions before checkout. No coupon code is claimed.','code':None,'offer_type':'auto-deal','badge':'AUTO DEAL','verified':0,'expires_at':None,'active':1,'source':'auto'}, {'title':f'Compare {category} prices on Amazon','description':'Search current products and offers on Amazon. Availability and prices can change.','code':None,'offer_type':'amazon','badge':'AMAZON','verified':0,'expires_at':None,'active':1,'source':'amazon'}]

def is_store_indexable(store, c):
    # The exact same predicate decides sitemap inclusion and page robots tags.
    where=store_sitemap_where(CURATED_STORE_INDEXING_ENABLED)
    return c.execute(f'SELECT 1 FROM stores s WHERE s.id=? AND {where}',
                     (store['id'],)).fetchone() is not None

def conn():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def clean_slug(value):
    value=(value or '').strip().lower(); value=re.sub(r'[^a-z0-9]+','-',value).strip('-'); return value

def init_db():
    os.makedirs(os.path.dirname(DB), exist_ok=True); c=conn()
    c.execute('''CREATE TABLE IF NOT EXISTS stores (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,slug TEXT NOT NULL UNIQUE,category TEXT DEFAULT 'Shopping',description TEXT,active INTEGER DEFAULT 1)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_stores_slug ON stores(slug)'); c.execute('CREATE INDEX IF NOT EXISTS idx_stores_name ON stores(name COLLATE NOCASE)')
    c.execute('''CREATE TABLE IF NOT EXISTS affiliate_networks (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, slug TEXT NOT NULL UNIQUE, priority INTEGER DEFAULT 100, active INTEGER DEFAULT 0, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS affiliate_merchants (id INTEGER PRIMARY KEY AUTOINCREMENT, network_id INTEGER NOT NULL, merchant_name TEXT NOT NULL, merchant_domain TEXT, merchant_external_id TEXT, status TEXT DEFAULT 'pending', UNIQUE(network_id, merchant_external_id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS store_affiliate_matches (id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER NOT NULL, network_id INTEGER NOT NULL, merchant_id INTEGER, affiliate_url TEXT, status TEXT DEFAULT 'pending', match_method TEXT DEFAULT 'manual', confidence REAL, created_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS affiliate_clicks (id INTEGER PRIMARY KEY AUTOINCREMENT, store_id INTEGER, match_id INTEGER, network_id INTEGER, clicked_at TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS search_events (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL, normalized_query TEXT NOT NULL, route_type TEXT NOT NULL, matched_slug TEXT, results_count INTEGER DEFAULT 0, created_at TEXT NOT NULL)''')
    c.execute('''CREATE TABLE IF NOT EXISTS offers (id INTEGER PRIMARY KEY AUTOINCREMENT,store_id INTEGER NOT NULL,title TEXT NOT NULL,description TEXT,code TEXT,offer_type TEXT DEFAULT 'code',badge TEXT DEFAULT 'OFFER',verified INTEGER DEFAULT 0,expires_at TEXT,active INTEGER DEFAULT 1,created_at TEXT)''')
    c.execute('CREATE INDEX IF NOT EXISTS idx_offers_store ON offers(store_id, active)'); c.execute('CREATE INDEX IF NOT EXISTS idx_match_store ON store_affiliate_matches(store_id, status)'); c.execute('CREATE INDEX IF NOT EXISTS idx_click_store ON affiliate_clicks(store_id)'); c.execute('CREATE INDEX IF NOT EXISTS idx_search_events_query ON search_events(normalized_query, created_at)')
    for priority, slug, name in [(1,'sovrn','Sovrn Commerce'),(2,'awin','Awin'),(3,'cj','CJ Affiliate'),(4,'impact','Impact'),(5,'rakuten','Rakuten Advertising'),(6,'ebay','eBay Partner Network')]: c.execute('INSERT OR IGNORE INTO affiliate_networks(name,slug,priority,active,created_at) VALUES (?,?,?,?,?)',(name,slug,priority,0,datetime.utcnow().isoformat()))
    count=c.execute('SELECT COUNT(*) FROM stores').fetchone()[0]
    if count==0 and os.path.exists(CSV_FILE):
        batch=[]; seen=set()
        with open(CSV_FILE,newline='',encoding='utf-8-sig',errors='ignore') as f:
            for row in csv.reader(f):
                if len(row)<2: continue
                name=row[0].strip(); slug=clean_slug(row[1])
                if not name or not slug or name.lower() in {'store name','name'} or slug in RESERVED: continue
                if slug in seen: continue
                seen.add(slug); batch.append((name,slug))
                if len(batch)>=5000: c.executemany('INSERT OR IGNORE INTO stores(name,slug) VALUES (?,?)',batch); c.commit(); batch=[]
        if batch: c.executemany('INSERT OR IGNORE INTO stores(name,slug) VALUES (?,?)',batch)
    c.commit(); c.close()

@app.context_processor
def globals_ctx(): return {'current_year':datetime.now().year,'site_name':'US Coupon Hub','states':STATES,'cities':CITIES,'categories':CATEGORIES,'format_number':lambda n:f'{n:,}'}

@app.after_request
def seo_response_headers(response):
    if request.path.startswith('/sitemap'):
        response.headers['Cache-Control']='public, max-age=3600, stale-while-revalidate=86400' if response.status_code==200 else 'no-store'
    if request.path in {'/search-insights/','/affiliate-status/'}:
        response.headers['X-Robots-Tag']='noindex, nofollow'
    return response

@app.route('/favicon.ico')
def favicon(): return app.send_static_file('favicon.ico')

@app.route('/')
def home():
    c=conn(); stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT 12').fetchall(); total=c.execute('SELECT COUNT(*) FROM stores WHERE active=1').fetchone()[0]; c.close(); return render_template('home.html',stores=stores,total=total)

def normalize_search_query(value):
    value=(value or '').strip().lower(); value=re.sub(r'\s+',' ',value); return value[:180]

def classify_search(c,q):
    normalized=normalize_search_query(q)
    if not normalized: return 'directory',None,0
    q_slug=clean_slug(normalized); exact=c.execute('SELECT * FROM stores WHERE active=1 AND (slug=? OR lower(name)=?) LIMIT 1',(q_slug,normalized)).fetchone()
    if exact: return 'store',exact['slug'],1
    category_slug=category_from_query(normalized)
    if category_slug: return 'category',category_slug,1
    pattern=f'%{normalized}%'; count=c.execute('SELECT COUNT(*) FROM stores WHERE active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?)',(pattern,pattern)).fetchone()[0]
    if count==1:
        one=c.execute('SELECT slug FROM stores WHERE active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?) LIMIT 1',(pattern,pattern)).fetchone()
        if one: return 'store',one['slug'],count
    return 'directory',None,count

def log_search(c,q,route_type,matched_slug=None,results_count=0):
    if not q: return
    c.execute('INSERT INTO search_events(query,normalized_query,route_type,matched_slug,results_count,created_at) VALUES (?,?,?,?,?,?)',(q[:180],normalize_search_query(q),route_type,matched_slug,results_count,datetime.utcnow().isoformat())); c.commit()

@app.route('/stores')
def stores_redirect(): return redirect('/stores/',code=301)

@app.route('/search/')
@app.route('/stores/')
def search_page():
    q=request.args.get('q','').strip()
    try: page=max(1,int(request.args.get('page',1)))
    except (TypeError,ValueError): page=1
    per_page=50; c=conn(); route_type,target,classified_count=classify_search(c,q)
    if q and route_type=='store' and target: log_search(c,q,'store',target,classified_count); c.close(); return redirect(url_for('store_page',slug=target))
    if q and route_type=='category' and target: log_search(c,q,'category',target,classified_count); c.close(); return redirect(url_for('category_page',category_slug=target))
    pattern=f'%{q}%'
    where='active=1 AND (name LIKE ? COLLATE NOCASE OR slug LIKE ?)' if q else 'active=1'
    params=(pattern,pattern) if q else ()
    total=c.execute(f'SELECT COUNT(*) FROM stores WHERE {where}',params).fetchone()[0]
    total_pages=max(1,(total+per_page-1)//per_page)
    page=min(page,total_pages)
    # Bound page before passing OFFSET to SQLite (huge integers caused 500s).
    raw_page=request.args.get('page')
    if raw_page is not None and (raw_page!=str(page) or page==1):
        c.close()
        args={'q':q} if q else {}
        if page>1: args['page']=page
        suffix=urlparse.urlencode(args)
        return redirect(request.path+('?' + suffix if suffix else ''),code=301)
    offset=(page-1)*per_page
    results=c.execute(f'SELECT * FROM stores WHERE {where} ORDER BY name COLLATE NOCASE, id LIMIT ? OFFSET ?',params+(per_page,offset)).fetchall()
    if q: log_search(c,q,'directory',None,total)
    page_links=sorted({1,total_pages,*range(max(1,page-2),min(total_pages,page+2)+1)})
    c.close(); return render_template('search.html',q=q,results=results,page=page,total=total,per_page=per_page,total_pages=total_pages,page_links=page_links)

@app.route('/search-insights/')
def search_insights():
    days=max(1,min(365,int(request.args.get('days',30)))); c=conn(); since=f'-{days} days'; summary=c.execute("SELECT COUNT(*) AS searches, COUNT(DISTINCT normalized_query) AS unique_queries FROM search_events WHERE created_at >= datetime('now', ?)",(since,)).fetchone(); top=c.execute("SELECT normalized_query, COUNT(*) AS volume, SUM(CASE WHEN route_type='store' THEN 1 ELSE 0 END) AS store_matches, SUM(CASE WHEN route_type='category' THEN 1 ELSE 0 END) AS category_matches, SUM(CASE WHEN route_type='ebay' THEN 1 ELSE 0 END) AS ebay_fallbacks FROM search_events WHERE created_at >= datetime('now', ?) AND normalized_query<>'' GROUP BY normalized_query ORDER BY volume DESC, normalized_query LIMIT 100",(since,)).fetchall(); c.close(); return render_template('search_insights.html',days=days,summary=summary,top=top)

@app.route('/<slug>/')
@app.route('/<slug>')
def store_page(slug):
    if slug in RESERVED: abort(404)
    c=conn(); store=c.execute('SELECT * FROM stores WHERE slug=? AND active=1',(slug,)).fetchone()
    if not store: c.close(); abort(404)
    if request.path.endswith('/'):
        c.close()
        return redirect(url_for('store_page',slug=store['slug']),code=301)
    first=(store['name'] or '')[:1]; related=c.execute('SELECT * FROM stores WHERE active=1 AND slug<>? AND name LIKE ? COLLATE NOCASE ORDER BY name LIMIT 6',(slug,f'{first}%')).fetchall()
    if len(related)<6:
        excluded=[store['id']]+[r['id'] for r in related]
        placeholders=','.join('?' for _ in excluded)
        extra=c.execute(f'SELECT * FROM stores WHERE active=1 AND id NOT IN ({placeholders}) ORDER BY name COLLATE NOCASE LIMIT ?',excluded+[6-len(related)]).fetchall(); related=list(related)+list(extra)
    db_offers=c.execute(f'SELECT o.* FROM offers o WHERE o.store_id=? AND {CURRENT_OFFER_WHERE} ORDER BY o.verified DESC, o.id DESC',(store['id'],)).fetchall(); offers=automatic_store_offers(store,db_offers); match=get_match(c,store['id']); store_indexable=is_store_indexable(store,c); c.close(); return render_template('store.html',store=store,related=related,offers=offers,affiliate_match=match,amazon_url=amazon_search_url(store['name']),store_indexable=store_indexable)

@app.route('/amazon/search/<slug>/')
def amazon_store_search(slug):
    if slug in RESERVED: abort(404)
    c=conn(); store=c.execute('SELECT * FROM stores WHERE slug=? AND active=1',(slug,)).fetchone(); c.close()
    if not store: abort(404)
    return redirect(amazon_search_url(store['name']),code=302)

@app.route('/go/<slug>/')
def affiliate_go(slug):
    if slug in RESERVED: abort(404)
    c=conn(); store=c.execute('SELECT * FROM stores WHERE slug=? AND active=1',(slug,)).fetchone()
    if not store: c.close(); abort(404)
    match=get_match(c,store['id']); destination=build_destination(match)
    if not destination: c.close(); return redirect(url_for('store_page',slug=slug))
    log_click(c,store['id'],match['id'],match['network_id']); c.close(); return redirect(destination,code=302)

@app.route('/ebay/search/')
def ebay_search_page():
    return Response('This marketplace search has been permanently retired.',status=410,headers={'X-Robots-Tag':'noindex, nofollow, noarchive'},content_type='text/plain; charset=utf-8')

@app.route('/ebay/debug/')
def ebay_debug():
    return Response('This diagnostic endpoint has been permanently retired.',status=410,headers={'X-Robots-Tag':'noindex, nofollow, noarchive'},content_type='text/plain; charset=utf-8')

@app.route('/ebay/account-deletion',methods=['GET','POST'])
@app.route('/ebay/account-deletion/',methods=['GET','POST'])
def ebay_account_deletion():
    endpoint=os.environ.get('EBAY_ACCOUNT_DELETION_ENDPOINT','https://uscouponhub.onrender.com/ebay/account-deletion').strip().rstrip('/'); verification_token=os.environ.get('EBAY_VERIFICATION_TOKEN','').strip(); challenge_code=(request.args.get('challenge_code') or request.args.get('challengeCode') or '').strip()
    if challenge_code:
        if not verification_token or not endpoint: return {'error':'Missing eBay verification configuration.'},500
        challenge_response=hashlib.sha256((challenge_code+verification_token+endpoint).encode('utf-8')).hexdigest(); return {'challengeResponse':challenge_response},200
    if request.method=='GET': return {'status':'eBay account deletion endpoint is ready','challenge_required':True},200
    return '',204

@app.route('/blog/how-to-check-promo-code')
@app.route('/blog/how-to-check-promo-code/')
def legacy_how_to_check_promo_code():
    return redirect('/guides/find-legit-promo-codes/',code=301)

@app.route('/blog')
def blog_redirect(): return redirect('/blog/',code=301)
@app.route('/blog/')
def blog_page(): return render_template('blog.html',posts=BLOG_POSTS)
@app.route('/blog/<post_slug>')
def blog_post_redirect(post_slug): return redirect(url_for('blog_post_page',post_slug=post_slug),code=301)
@app.route('/blog/<post_slug>/')
def blog_post_page(post_slug):
    post=BLOG_POSTS.get(post_slug)
    if not post: abort(404)
    return render_template('blog_post.html',post=post,post_slug=post_slug)
@app.route('/guides/')
def guides_page(): return render_template('guides.html',guides=SHOPPING_GUIDES)
@app.route('/guides/<guide_slug>/')
def guide_page(guide_slug):
    guide=SHOPPING_GUIDES.get(guide_slug)
    if not guide: abort(404)
    return render_template('guide.html',guide=guide,guide_slug=guide_slug)
@app.route('/about/')
def about_page(): return render_template('about.html')
@app.route('/privacy/')
def privacy_page(): return render_template('privacy.html')
@app.route('/terms/')
def terms_page(): return render_template('terms.html')
@app.route('/disclaimer/')
def disclaimer_page(): return render_template('disclaimer.html')
@app.route('/contact/')
def contact_page(): return render_template('contact.html')
@app.route('/affiliate-disclosure/')
def affiliate_disclosure(): return render_template('affiliate_disclosure.html')
@app.route('/affiliate-status/')
def affiliate_status(): c=conn(); networks=get_networks(c); c.close(); return render_template('affiliate_status.html',networks=networks)
@app.route('/states/<state_slug>/')
def state_page(state_slug):
    if state_slug not in STATES: abort(404)
    c=conn(); stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT 18').fetchall(); c.close(); return render_template('state.html',state=STATES[state_slug],stores=stores)
@app.route('/cities/<city_slug>/')
def city_page(city_slug):
    if city_slug not in CITIES: abort(404)
    c=conn(); stores=c.execute('SELECT * FROM stores WHERE active=1 ORDER BY name COLLATE NOCASE LIMIT 12').fetchall(); c.close(); return render_template('city.html',city=CITIES[city_slug],stores=stores)
@app.route('/categories/<category_slug>/')
def category_page(category_slug):
    if category_slug not in CATEGORIES: abort(404)
    cfg=CATEGORY_CONFIG.get(category_slug,{'label':category_slug.replace('-',' ').title(),'query':category_slug.replace('-',' '),'subcategories':[]}); category=cfg['label']; c=conn(); stores=c.execute('SELECT * FROM stores WHERE active=1 AND lower(category)=? ORDER BY name COLLATE NOCASE LIMIT 24',(category.lower(),)).fetchall()
    if not stores:
        words=[w for w in re.split(r'[^a-z0-9]+',cfg['query'].lower()) if len(w)>2]; aliases=cfg.get('aliases',[]); terms=list(dict.fromkeys(words+aliases))[:8]; clauses=' OR '.join(['lower(name) LIKE ?' for _ in terms]); params=[f'%{term.lower()}%' for term in terms]
        if clauses: stores=c.execute(f'SELECT * FROM stores WHERE active=1 AND ({clauses}) ORDER BY name COLLATE NOCASE LIMIT 24',params).fetchall()
    c.close(); return render_template('category.html',category=category,category_slug=category_slug,stores=stores,subcategories=cfg.get('subcategories',[]),ebay_items=[],ebay_error=None,ebay_query='')
@app.route('/seasonal/<event_slug>/')
def seasonal_page(event_slug):
    if event_slug not in SEASONAL_EVENTS: abort(404)
    return render_template('seasonal.html',event=SEASONAL_EVENTS[event_slug])

@app.route('/sitemap.xml')
def sitemap_index():
    c=conn(); where=store_sitemap_where(CURATED_STORE_INDEXING_ENABLED); total=c.execute(f'SELECT COUNT(*) FROM stores s WHERE {where}').fetchone()[0]; c.close(); parts=(total+49999)//50000; base='https://uscouponhub.com'; return Response('<?xml version="1.0" encoding="UTF-8"?>\n<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<sitemap><loc>{base}/sitemap-stores-{i}.xml</loc></sitemap>' for i in range(1,parts+1))+f'<sitemap><loc>{base}/sitemap-static.xml</loc></sitemap></sitemapindex>',mimetype='application/xml')
@app.route('/sitemap-static.xml')
def sitemap_static():
    base='https://uscouponhub.com'; urls=[f'{base}/',f'{base}/stores/',f'{base}/guides/',f'{base}/about/',f'{base}/privacy/',f'{base}/terms/',f'{base}/disclaimer/',f'{base}/contact/',f'{base}/affiliate-disclosure/']+[f'{base}/guides/{slug}/' for slug in SHOPPING_GUIDES]+[f'{base}/blog/']+[f'{base}/blog/{slug}/' for slug in BLOG_POSTS]+[f'{base}/states/{s}/' for s in STATES]+[f'{base}/cities/{x}/' for x in CITIES]+[f'{base}/categories/{x}/' for x in CATEGORIES]+[f'{base}/seasonal/{slug}/' for slug in SEASONAL_EVENTS]; return Response('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{u}</loc></url>' for u in urls)+'</urlset>',mimetype='application/xml')
@app.route('/sitemap-stores-<int:part>.xml')
def sitemap_stores(part):
    if part < 1 or part > 1+(2**63-1)//50000: abort(404)
    per=50000; offset=(part-1)*per; where=store_sitemap_where(CURATED_STORE_INDEXING_ENABLED); c=conn(); rows=c.execute(f'SELECT s.slug FROM stores s WHERE {where} ORDER BY s.id LIMIT ? OFFSET ?',(per,offset)).fetchall(); c.close(); base='https://uscouponhub.com'
    if not rows: abort(404)
    return Response('<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{base}/{r["slug"]}</loc></url>' for r in rows)+'</urlset>',mimetype='application/xml')
@app.route('/robots.txt')
def robots():
    body='\n'.join(['User-agent: *','Allow: /','Disallow: /go/','Disallow: /amazon/search/','Disallow: /ebay/search/','Disallow: /ebay/debug/','Sitemap: https://uscouponhub.com/sitemap.xml',''])
    return Response(body,mimetype='text/plain')
init_db()
if __name__=='__main__': app.run(debug=True)
