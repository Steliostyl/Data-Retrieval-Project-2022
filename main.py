from elasticsearch import Elasticsearch
from pprint import pprint
import elastic
import functions
import clustering
import network
import json
import timeit

PROCESSED_FILES = "Files/Processed/"

ES_REPLY = PROCESSED_FILES + "ES-Reply.json"
PROC_USERS = PROCESSED_FILES + "Processed-Users.csv"
CLUSTER_ASSIGNED_USERS = PROCESSED_FILES + "Cluster-Assigned-Users.csv"
AVG_CLUSTER_RATINGS = PROCESSED_FILES + "Average-Cluster-Rating.csv"
BOOKS_VECTORIZED_SUMMARIES = PROCESSED_FILES + "Books-Vectorized-Summaries.csv"

OUTPUT_FILES = "Files/Output/"

SCORES_NO_CLUST = OUTPUT_FILES + "Scores-No-Clustering.csv"
SCORES_W_CLUST = OUTPUT_FILES + "Scores-With-Clustering.csv"

ES_PASSWORD = "-wq4MlKQgAgo+fnKLy=U"
CERT_FINGERPRINT = "dd:4d:bc:9e:34:74:70:c5:8c:c9:40:b6:eb:d8:c7:89:07:dd:2e:fa:ff:a2:f7:62:aa:52:79:10:6c:60:7a:9a"

def _input(message, input_type=str):
    """Helper function that forces user
    to enter a predefined type of input."""

    while True:
        try:
            return input_type (input(message))
        except: pass

def main():
    ############################ ELASTICSEARCH #############################
    
    # Connect to the ElasticSearch cluster
    es = Elasticsearch(
        "http://localhost:9200",
        ssl_assert_fingerprint=CERT_FINGERPRINT,
        basic_auth=("elastic", ES_PASSWORD)
        )

    # Create a new index in ElasticSearch called books
    print("Creating books index...")
    elastic.createIndex(es, idx_name="books")

    # Insert a sample of data from dataset into ElasticSearch
    book_count = elastic.insertData(es)[0]["count"]
    print(f"Inserted {book_count} books into index.")

    # Input query parameters and make query to ES
    search_string = input("Enter search string:")
    user_id = _input("Enter your user ID (must be an integer): ", int)
    es_reply = elastic.makeQuery(es, search_string)

    # Save ES reply to a JSON file
    with open(ES_REPLY, "w") as output:
        json.dump(es_reply["hits"], output, indent=2)

    # Print results summary
    print(f"\nElasticsearch returned {len(es_reply['hits'])} books. The 5 best matches are:")
    pprint([[book['_score'], book["_source"]['book_title']] for book in es_reply["hits"][:5]])

    # Get the combined scores for all replies
    print("\nCalculating combined scores...")
    combined_scores = functions.calculateCombinedScores(es_reply, user_id)
    combined_scores.to_csv(SCORES_NO_CLUST, index=False)

    # Print the scores of the 5 best matches
    print("\nBest 5 matches without clustering:\n")
    print(combined_scores.head(5))

    input("\nPress enter to continue to Clustering...\n")

    ############################## CLUSTERING ##############################

    # Create a CSV containing users sorted by their country
    # Entries that have a high chance of being fake are ignored
    print("Creating processed users CSV...")
    processed_users = functions.processUsersCSV()
    processed_users.to_csv(PROC_USERS, index=False)
    print(processed_users.head(5))

    # Plot elbow curve to help determine optimal number of clusters
    print("\nPlotting elbow curve...")
    clustering.plot_elbow_curve(2, 12, 10_000, processed_users)
    k = _input("Choose number of clusters to use: ", int)

    # Run and time k-Prototypes
    print("Starting clustering...")
    start_time = timeit.default_timer()
    cluster_assigned_users = clustering.kPrototypes(k, processed_users)
    elapsed_time = timeit.default_timer() - start_time
    cluster_assigned_users.to_csv(CLUSTER_ASSIGNED_USERS, index=False)
    print(f"Clustering with {k} clusters took {int(elapsed_time//60)}\
        minutes and {int(round(elapsed_time % 60, 0))} seconds.")

    # Create a dataframe containing the average
    # rating of every book per cluster
    print("Creating average cluster ratings CSV...")
    avg_clust_ratings = functions.createAvgClusterRatings(cluster_assigned_users)
    avg_clust_ratings.to_csv(AVG_CLUSTER_RATINGS)

    # Get the re-calculated document scores by using
    # user's cluster's average ratings to "rate" unrated books
    print("Re-calculating combined scores using user's cluster's average book ratings...")
    combined_scores_clusters_df = functions.calculateCombinedScores(es_reply, user_id,\
        use_cluster_ratings=True, avg_clust_ratings = avg_clust_ratings,\
            cluster_assigned_users = cluster_assigned_users)
    combined_scores_clusters_df.to_csv(SCORES_W_CLUST, index=False)
    
    ############################## NEURAL NETWORK ##############################

    # Turn summaries into vectors to be used as input for the network
    vectorized_summaries = network.vectorizeSummaries()
    vectorized_summaries.to_csv(BOOKS_VECTORIZED_SUMMARIES, index=False)
    print("Finished vectorizing summaries.")

if __name__ == "__main__":
    main()