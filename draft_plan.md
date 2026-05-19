A web application with the following requirements:

The app receives a video input and extracts it into two parts:

* Full audio
* Frames extracted every 5 frames

1. Audio Processing

* Convert the extracted audio into text and save it as `transcript.txt`

* Check whether `transcript.txt` exceeds 5000 tokens:

  * If yes:

    * Create a file named `summary.md`
    * Set a local variable: `summary = true`
  * Otherwise:

    * Set `summary = false`

* `summary.md` must summarize the entire transcript hierarchically:

  * Main topics
  * Major ideas
  * Sub-ideas

2. Image Processing

* Not required for now

3. Query and Question Answering

* An OpenAI API reads:

  * the entire `transcript.txt` if `summary = false`
  * otherwise only `summary.md`

* The API must determine and output:

  * `parent_topic`
  * `main_topic`

Definitions:

* `parent_topic` = the broad domain/category of the video
* `main_topic` = the direct/specific topic of the video

Example:

* If the video is about vocal training or piano:

  * `parent_topic = "music"`

* Add another OpenAI API with the following prompt:

```python
prompt = f"""
You are an expert in {parent_topic}.

Below is information extracted from a video about {main_topic}:

{summary.md content if available, otherwise transcript.txt}

Use both your own knowledge and the information from the video to answer the following question:

{question}

RULES:
- This is NOT retrieval-based answering.
- Answer using understanding and expertise.
- Information from the video should support and clarify the answer,
  but you are allowed to use outside knowledge when necessary.

Return:
Answer: ""
Need_Search: True or False
Search_Query: None if search is not needed
"""
```

* Add an additional search/retrieval step for supplementary information
* Add one more API to generate the final refined answer
