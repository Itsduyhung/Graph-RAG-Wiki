# import time
# from pipeline.query_pipeline import QueryPipeline

# def timed_process_query(question: str) -> tuple[str, dict]:
#     pipeline = QueryPipeline()
    
#     start_time = time.perf_counter()
    
#     print(f"\n{'='*60}")
#     print(f"📝 Query: {question}")
#     print(f"{'='*60}")
    
#     # Step 1
#     step1_start = time.perf_counter()
#     print("\n[1/5] Query Understanding...")
#     query_info = pipeline._understand_query(question)
#     step1_end = time.perf_counter()
#     print(f"  Entity: {query_info['entity']}")
#     print(f"  Intent: {query_info['intent']}")
#     print(f"  ⏱️ Step 1: {step1_end - step1_start:.3f}s")
    
#     # Step 2
#     step2_start = time.perf_counter()
#     print("\n[2/5] Candidate Retrieval...")
#     candidates = pipeline._retrieve_candidates(query_info)
#     step2_end = time.perf_counter()
#     print(f"  Found {len(candidates)} candidates")
#     print(f"  ⏱️ Step 2: {step2_end - step2_start:.3f}s")
    
#     # Step 3
#     step3_start = time.perf_counter()
#     print("\n[3/5] Graph Expansion...")
#     expanded = pipeline._expand_graph(candidates)
#     step3_end = time.perf_counter()
#     print(f"  Expanded to {len(expanded)} nodes")
#     print(f"  ⏱️ Step 3: {step3_end - step3_start:.3f}s")
    
#     # Step 4
#     step4_start = time.perf_counter()
#     print("\n[4/5] Context Filtering...")
#     context = pipeline._filter_context(query_info, expanded)
#     step4_end = time.perf_counter()
#     print(f"  Context length: {len(context)} chars")
#     print(f"  ⏱️ Step 4: {step4_end - step4_start:.3f}s")
    
#     # Step 5
#     step5_start = time.perf_counter()
#     print("\n[5/5] Answer Generation...")
#     answer = pipeline._generate_answer(query_info, context)
#     step5_end = time.perf_counter()
#     print(f"  ⏱️ Step 5: {step5_end - step5_start:.3f}s")
    
#     total_time = time.perf_counter() - start_time
#     print(f"\n{'='*60}")
#     print(f"🎯 Total time: {total_time:.3f}s")
#     print(f"{'='*60}")
    
#     timing = {
#         'step1': step1_end - step1_start,
#         'step2': step2_end - step2_start,
#         'step3': step3_end - step3_start,
#         'step4': step4_end - step4_start,
#         'step5': step5_end - step5_start,
#         'total': total_time
#     }
    
#     return answer, timing

# if __name__ == "__main__":
#     question = "Bảo Đại tên thật là gì?"
#     answer, timing = timed_process_query(question)
#     print(f"\nAnswer: {answer}")
#     print(f"Timing: {timing}")

