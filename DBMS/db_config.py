import mysql.connector

def get_db_connection():
    connection = mysql.connector.connect(
        host="localhost",
        user="library_user",        # Replace with your MySQL username
        password="Stop@scam1",      # Replace with your MySQL password
        database="library_db"       # Replace with your MySQL database name
    )
    return connection
