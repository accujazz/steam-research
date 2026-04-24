## About
Building a Streamlit dashboard for Steam game market research. The dashboard fetches data from Steam APIs, calculates estimated revenue, wishlists, and displays results in a sortable table with charts. Useful for genre analysis.

![Screenshot](/steam-genre-research.png)

## Uses
- Steam popular tags list with name -> tagid mapping
- Steam search API for paginated game discovery
- Steam store API for game details
- Steam review API to get review counts
- Steam community group XML for follower counts

## Fields
- appid
- name
- url
- reviews (total), (30d - shows which games got the most
  traction at launch), (1y), (3y)
- score (positive / (positive + negative). A game with 900 positive and 100 negative reviews gets 0.90.)
- initial price
- revenue estimate (total), (30d), (1y), (3y)
- wishlists estimate
- followers
- is early access?
- release date
- tags

No third party services other than Steam itself are being used for data.

## Run locally
1. Install dependencies
	- python3 -m pip install -r requirements.txt
2. Run the app
	- python3 -m streamlit run app.py

The app opens at http://localhost:8501

## Usage
1. Define your target genres via Steam tags.
2. Go to [SteamDB Tag Explorer](https://steamdb.info/tags/), select relevant games and copy their App IDs.
2. Paste App IDs from the previous step or target genres into the Data Source sidebar section.
3. Fetch Data.
4. Filter for revelance if needed. Parameters to consider:
	- Market relevance (Release date > 2020)
	- Reviews > 100