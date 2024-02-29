import streamlit as st
import pdfplumber
import base64
import boto3
import pandas as pd
import os
from urllib.parse import urlparse, quote

from sentence_transformers import SentenceTransformer
from qdrant_client import QdrantClient
from qdrant_client.http import models
from botocore.exceptions import ClientError
from botocore.client import Config
api_key=st.secrets["QDRANT_API_KEY"]
public_url = "https://pub-e35f1eea0f994d01831e4b2431dc977c.r2.dev"



def modify_pdf_url(original_url, new_base_url,page_number):
    # Parse the original URL
    parsed_url = urlparse(original_url)

    # Extract the path and optionally any query parameters or fragments
    url_path = parsed_url.path
    if parsed_url.query:
        url_path += '?' + parsed_url.query
    if parsed_url.fragment:
        url_path += '#' + parsed_url.fragment

    # URL-encode the extracted path
    encoded_path = quote(url_path)

    # Concatenate the new base URL with the encoded path
    modified_url = new_base_url.rstrip('/') + '/' + encoded_path

    return modified_url.replace("/pharma/","")+"#page=%s" % page_number


def perform_search(query,collection):
    encoded_query = encoder.encode(query).tolist()
    hits = qclient.search(
        collection_name=collection,
        query_vector=encoded_query,
        limit=3,
    )
    sorted_hits = sorted(hits, key=lambda x: x.score, reverse=True)
    results = [{
        "URL": hit.payload["file_url"],
        "Score": hit.score,
        "Page Number": hit.payload["page_number"]
    } for hit in hits]
    return results

def read_pdf(pdf_path):
    contents = []
    with pdfplumber.open(pdf_path) as pdf:
        # loop over all the pages
        for (i,page) in enumerate(pdf.pages):
            contents.append([i,page.extract_text()])
    return contents

def upload_file_to_cloudflare_r2(client, bucket_name, file_object):
    """
    Uploads a file to Cloudflare R2 bucket if it does not already exist.

    Parameters:
        client (boto3.client): The boto3 client configured for Cloudflare R2.
        bucket_name (str): The name of the bucket where the file will be uploaded.
        file_object: The file object to upload, typically from Streamlit's file_uploader.

    Returns:
        str: The URL of the uploaded file or an error message.
    """
    file_name = file_object.name
    file_content = file_object.getvalue()

    try:
        # Check if the file already exists in the bucket
        client.head_object(Bucket=bucket_name, Key=file_name)
        return "A file with this name already exists."
    except ClientError as e:
        if e.response['Error']['Code'] == '404':
            # The file does not exist, proceed with upload
            try:
                client.put_object(Bucket=bucket_name, Key=file_name, Body=file_content)
                file_url = f"{client.meta.endpoint_url}/{bucket_name}/{file_name}"
                return file_url
            except Exception as ex:
                return f"Failed to upload file: {str(ex)}"
        else:
            # An unexpected error occurred
            return f"Error checking file existence: {str(e)}"

# Initialize the S3 client for Cloudflare R2
access_key = st.secrets["ACCESS_KEY"]
secret_key = st.secrets["SECRET_KEY"]
r2_endpoint_url = 'https://4da7499998832558c2f0ba2a167c4ca6.r2.cloudflarestorage.com/pharma'

session = boto3.session.Session()
client = session.client(
    's3',
    region_name='auto',
    endpoint_url=r2_endpoint_url,
    aws_access_key_id=access_key,
    aws_secret_access_key=secret_key,
    config=Config(signature_version='s3v4')
)

from qdrant_client.models import VectorParams, Distance
qclient = QdrantClient("https://21bf5bc7-6b18-4a47-a088-438c32c94750.us-east4-0.gcp.cloud.qdrant.io",api_key=api_key)
encoder = SentenceTransformer("all-MiniLM-L6-v2")
model = SentenceTransformer(
    "all-MiniLM-L6-v2"
)  # or device="cpu" if you don't have a GPU

# Function to generate a PDF display URL
def generate_pdf_display(uploaded_file, start_page=1):
    base64_pdf = base64.b64encode(uploaded_file.getvalue()).decode('utf-8')
    pdf_display = f"""
        <iframe src="data:application/pdf;base64,{base64_pdf}#page={start_page}" width="700" height="1000" type="application/pdf"></iframe>
    """
    return pdf_display

def main():
    if 'file_uploaded' not in st.session_state:
        st.session_state.file_uploaded = False
    if 'selected_pdf_url' not in st.session_state:
        st.session_state['selected_pdf_url'] = ""
    if 'search_results' not in st.session_state:
        st.session_state["search_results"] = ""
    # Define your tabs
    category = st.selectbox("Select Category", ["Legislation", "Background Reading"])
    tab1, tab2 = st.tabs(["Search", "File Upload"])
    
    with tab1:
        st.header("Search")
        query = st.text_input("Enter your search query:", "")

        if st.button("Search"): 
            st.session_state["clicked_button"] = None
            st.session_state["search_results"] = perform_search(query,category)
        if st.session_state["search_results"]:
            search_results = st.session_state["search_results"]
            header_cols = st.columns([2, 2, 1, 1])  # Adjust the number of columns based on your data
            header_cols[0].write("URL")
            header_cols[1].write("Score")
            header_cols[2].write("Page Number")
            # Display each search result with a "Show Me" button
            for index, result in enumerate(search_results):
                cols = st.columns([2, 2, 1, 1])  # Adjust the column widths as necessary
                cols[0].write(result["URL"].rsplit("/")[-1])
                cols[1].write(result["Score"])
                cols[2].write(result["Page Number"])
            options = [f"{result['URL']} - Score: {result['Score']}" for result in search_results]
            selected_option = st.selectbox("Select a result to view:", options)
            # Find the corresponding result
            selected_index = options.index(selected_option)
            selected_result = search_results[selected_index]
            page_number = selected_result.get("Page Number")
                            # Modify the PDF URL
            original_pdf_url = selected_result["URL"]
            new_base_url = "https://pub-e35f1eea0f994d01831e4b2431dc977c.r2.dev"
            pdf_url = modify_pdf_url(original_pdf_url, new_base_url,page_number)
            st.session_state['selected_pdf_url'] = modify_pdf_url(original_pdf_url, new_base_url, page_number)
        if st.session_state['selected_pdf_url']:
            st.markdown(f'<iframe src="{st.session_state["selected_pdf_url"]}" width="100%" height="500" style="border:none;"></iframe>',unsafe_allow_html=True)
                    
        
    with tab2:
        st.header("File Upload")

        if not st.session_state.file_uploaded:
            # File uploader widget
            uploaded_file = st.file_uploader("Choose a PDF file", type=['pdf'])
            if uploaded_file is not None:
                st.success("File successfully uploaded.")
                # Metadata input fields
                st.subheader("Enter Metadata - unused for now but we could add country or useful stuff to filter on later")
                Country= st.text_input("Country")
                description = st.text_area("Description")

                # Submit button for the metadata
                submit_button = st.button("Save File and Metadata")
                if submit_button:
                    with st.spinner('Processing your file, please wait...'):
                        result_message = upload_file_to_cloudflare_r2(client, "documents", uploaded_file)
                        if result_message.startswith("http"):
                            st.session_state.file_uploaded = True
                            pdf_contents = read_pdf(uploaded_file)
                            df= pd.DataFrame.from_records(pdf_contents,columns=["page","content"])
                            try:                            
                                qclient.create_collection(
                                    collection_name=category,
                                    vectors_config=models.VectorParams(
                                    size=encoder.get_sentence_embedding_dimension(),  # Vector size is defined by used model
                                    distance=models.Distance.COSINE,
                                    )
                                )
                            except:
                                print("already have")
                            qclient.upload_records(
                                collection_name=category,
                                records=[
                                    models.Record(
                                        id=id, vector=encoder.encode(doc["content"]).tolist(), payload={"file_url" :result_message ,"page_number" : doc["page"],"content" : doc["content"]}
                                    )
                                    for id, doc in df.iterrows()
                                ],
                            )
                        else:
                            st.error(result_message)
        if st.session_state.file_uploaded:
            st.success("File and metadata saved successfully!")
            if st.button("Upload another file"):
                st.session_state.file_uploaded = False
                # This will clear the file uploader and reset the form
                st.rerun()

main()
