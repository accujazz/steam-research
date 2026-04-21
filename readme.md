Building a Streamlit dashboard for Steam game market research. The dashboard fetches data from Steam APIs, calculates estimated revenue, wishlists, and displays results in a sortable table with charts. Useful for genre analysis.

Uses:
- Steam popular tags list with name -> tagid mapping
- Steam search API for paginated game discovery
- Steam store API for game details
- Steam review API to get review counts
- Steam community group XML for follower counts

Fields:
- appid
- name
- url
- reviews (total), (30d), (1y), (3y)
- score (positive / (positive + negative). A game with 900 positive and 100 negative reviews gets 0.90.)
- initial price
- revenue estimate (total), (30d), (1y), (3y)
- wishlists estimate
- followers
- is early access?
- release date
- tags

No third party tools other than Steam itself are being used.

## Run locally
python3 -m streamlit run app.py

## Usage
1. Define relevant App IDs or Steam tags that represent a targeted game niche. 
2. Fetch data.
3. Filter for revelance. Parameters to consider:
	- Market relevance (Release date > 2020)
	- Reviews > 100 (a hard coded filter for now, todo: make an user adjustable setting)