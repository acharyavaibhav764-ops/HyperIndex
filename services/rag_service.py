from core import Generator, Retriever
from schemas.query import QueryResponse, SourceItem


class RAGService:
    """
        Class to run the entire pipeline from the core modules

        Attributes:
            retriever
            generator
            retriever_k
        
        Methods:
            answer_question()
    """

    def __init__(
        self,
        retriever: Retriever,
        generator: Generator,
        retrieval_k: int = 5,
    ):
        self.retriever = retriever
        self.generator = generator
        self.retrieval_k = retrieval_k

    def answer_question(self, question: str) -> QueryResponse:
        q = question.strip() if question else ""
        if not q:
            raise ValueError("Question must not be empty")

        # Retrieve relevant chunks
        retrieved = self.retriever.retrieve(q, k=self.retrieval_k)
        documents = retrieved.get("documents", [[]])[0]
        metadatas = retrieved.get("metadatas", [[]])[0]
        distances = retrieved.get("distances", [[]])[0]

        if not documents:
            raise ValueError("No indexed document chunks were found for this query")

        # Build prompt and generate response with local Ollama
        prompt = self.generator.build_prompt(q, documents, metadatas)
        answer = self.generator.generate(prompt)

        # Return response
        return QueryResponse(
            question=q,
            answer=answer,
            model=self.generator.model,
            sources=[
                SourceItem(metadata=metadata, distance=distance)
                for metadata, distance in zip(metadatas, distances)
            ],
        )

