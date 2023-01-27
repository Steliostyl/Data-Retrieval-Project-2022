from csv import reader
import re
import sys
import pandas as pd

# Paths
INPUT_FILES = "Files/Input/"

USERS = INPUT_FILES + "BX-Users.csv"
RATINGS = INPUT_FILES + "BX-Book-Ratings.csv"
BOOKS = INPUT_FILES + "BX-Books.csv"

USER_R_WEIGHT = 1.1
ES_WEIGHT = 1

# Maximum valid age. Higher ages are considered false entries.
MAX_AGE = 120
MED_AGE = MAX_AGE / 2
# Minimum population of a (probably) valid country.
MIN_VAL_POP = 2
# Rating to use when rating is not found (out of 10)
DEFAULT_RAT = 5

def combinedScoreFunc(norm_es_score: float, user_rating: float) -> float:
    """Function that accepts as inputs the elastic search score of a book, the max score,
    as well as the user's rating of the book and returns a combined score."""

    # Add the normalized and weighted scores and scale them in the range [-10, 10]
    combined_score = ((ES_WEIGHT * norm_es_score) + (USER_R_WEIGHT * user_rating)) / (USER_R_WEIGHT + ES_WEIGHT)
    return combined_score

def calculateCombinedScores(es_reply: dict, user_id: int, use_cluster_ratings: bool = False,\
    avg_clust_ratings: pd.DataFrame = None, cluster_assigned_users_df: pd.DataFrame = None) -> pd.DataFrame:
    """Function that accepts as inputs the reply from ElasticSearch, user's id
    and all of their ratings and returns a sorted list of documents with the
    updated combined scores, which are calculated using the combinedScoreFunc."""

    books = es_reply["hits"]
    max_score = es_reply["max_score"]
    user_ratings_df = getUserRatings(user_id)
    print(f"User {user_id} has rated {len(user_ratings_df)} book(s).")

    # List to be filled with book entries
    # and their combined scores
    books_list = []
    users_cluster = -1

    # Get user's cluster
    if use_cluster_ratings:
        try:
            users_cluster = cluster_assigned_users_df["Cluster"].loc[cluster_assigned_users_df["User_ID"] == user_id].iloc[0]
            print(f"User {user_id} belongs in cluster {users_cluster}")
        except:
            print(f"User {user_id} doesn't exist in database. \nScores with clustering will be the same as scores without clustering.")

    # Iterate through the documents of the ES reply
    for book in books:
        isbn = book["_source"]["isbn"]
        norm_es_score = 10*book["_score"]/max_score
        
        # User has rated book
        try:
            # Get user's book rating and typecast it to float (from string)
            user_rating = float(user_ratings_df.loc[user_ratings_df["isbn"] == isbn]["rating"].iloc[0])
        # User has not rated this book
        except:
            # User doesn't exist in the database or function has 
            # been called with arg use_cluster_ratings = False
            if users_cluster == -1:
                user_rating = DEFAULT_RAT
            else:
                user_rating = getAvgClusterRating(users_cluster, isbn, avg_clust_ratings)
    
        # Combined score will be calculated using combinedScoreFunc
        score = combinedScoreFunc(norm_es_score, user_rating)
        # Create a new book entry as a list
        new_book = [score, user_rating, norm_es_score, isbn, book['_source']["book_title"], book['_source']["book_author"], book['_source']["year_of_publication"], book['_source']["publisher"], book['_source']["summary"], book['_source']["category"]]
        books_list.append(new_book)

    # Create a new dataframe from books_list and sort it by score
    best_matches = pd.DataFrame(data=books_list, columns=["score", "user_rating", "es_scaled_score", "isbn", "book_title", "book_author" , "year_of_publication", "publisher", "summary", "category"])\
        .sort_values(by="score", ascending=False)

    # Only keep the best 10% documents
    return best_matches.head(len(best_matches.index)//10)

def processUsersCSV() -> pd.DataFrame:
    """Extract vital information from BX-Users csv and save it to a new CSV."""
    # Create empty users dictionary
    users = []
    countries = []

    # Open users CSV in read mode
    with open(USERS, 'r') as input_file:
        csv_reader = reader(input_file, sys.stdout, skipinitialspace=True, lineterminator='\n')
        # Skip first line (headers)
        _ = next(csv_reader)

        # Iterate the lines of the csv
        for uid, location, age in csv_reader:
            uid = int(uid)
            try: 
                age = int(float(age))
                if age > MAX_AGE:
                    age = MED_AGE
            except: 
                age = MED_AGE
                
            # Extract country from location string
            country = re.findall(r"[\s\w+]+$", location)
            if not country:
                country = ""
                country_id = 500 + uid
            else:
                country = country[0][1:]

            # If country isn't already a key in users_by_country
            if country not in countries:
                country_id = len(countries)
                countries.append(country)
            else:
                country_id = countries.index(country)

            users.append([uid, age, country, country_id])
    
        users_df = pd.DataFrame(users, columns=["User_ID", "Age", "Country", "Country_ID"])
        
        return users_df

def createAvgClusterRatings(cluster_assignement_df: pd.DataFrame) -> pd.DataFrame:
    """Function that accepts as input the cluster assignement DataFrame and restores User IDs to it.
    Then, it combines this DF with the Book-Ratings CSV, averaging out the book ratings per cluster.
    The combined DF contains the columns isbn, cluster and rating and is finally returned."""

    # Open book ratings CSV in read mode
    books_ratings_df = pd.read_csv(RATINGS)
    # Merge the two DataFrames on UIDs
    result = pd.merge(right=books_ratings_df, left=cluster_assignement_df,\
        how="left", left_on="User_ID", right_on="uid", validate="one_to_many")
    # Drop useless columns
    result.drop(["uid", "User_ID", "Country", "Country_ID", "Age"], axis=1, inplace=True)
    # Group ratings by isbn and Cluster and sort resulting DataFrame
    avg_cluster_ratings = result.groupby(["isbn", "Cluster"]).mean().sort_values(by=["isbn", "Cluster"])
    #avg_cluster_ratings = avg_cluster_ratings.mean().sort_values(by=["isbn", "Cluster"])

    return avg_cluster_ratings

def getAvgClusterRating(users_cluster: int, isbn: str, avg_clust_ratings: pd.DataFrame) -> tuple:
    """Given a user id and an book's isbn, it returns the average rating of user's cluster for the specified book."""

    # Try getting user's cluster's rating of specified book
    try:
        rating = avg_clust_ratings.loc[(avg_clust_ratings["isbn"] == isbn) & (avg_clust_ratings["Cluster"] == users_cluster)]["rating"].iloc[0]
        #print(rating)
        return rating
    # If a book hasn't been rated by a cluster, return the median value of 5 stars out of 10
    except:
        return DEFAULT_RAT

def getUserRatings(user_id: int, filename: str = RATINGS) -> pd.DataFrame:
    """Read ratings CSV and return specified user's ratings."""

    users_ratings_df = pd.read_csv(filename)
    return  users_ratings_df.loc[users_ratings_df["uid"] == user_id]