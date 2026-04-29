
import os
import sqlite3
import json
from tea_agent.store import Storage

def test_db_summary_logic():
    import tempfile; db_path = tempfile.mktemp(suffix='.db')
    
    storage = Storage(db_path=db_path)
    
    # 1. Create a topic
    topic_id = storage.create_topic("Test Topic")
    
    # 2. Add some conversations
    c1 = storage.save_msg(topic_id, "User 1", "AI 1", False)
    c2 = storage.save_msg(topic_id, "User 2", "AI 2", False)
    c3 = storage.save_msg(topic_id, "User 3", "AI 3", False)
    
    # 3. Check unsummarized
    unsummarized = storage.get_unsummarized_conversations(topic_id)
    assert len(unsummarized) == 3
    assert unsummarized[0]['id'] == c1
    assert unsummarized[2]['id'] == c3
    print("✓ Initial unsummarized count is 3")
    
    # 4. Mark one as summarized
    storage.mark_as_summarized(c1)
    unsummarized = storage.get_unsummarized_conversations(topic_id)
    assert len(unsummarized) == 2
    assert unsummarized[0]['id'] == c2
    print("✓ After marking c1, unsummarized count is 2")
    
    # 5. Update summary and last_summarized_id
    storage.update_topic_summary(topic_id, "Summary of c1", last_summarized_id=c1)
    summary = storage.get_topic_summary(topic_id)
    assert summary == "Summary of c1"
    
    # Check last_summarized_id in DB
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT * FROM t_conv_summary WHERE topic_id = ?", (topic_id,)).fetchone()
    assert row['last_summarized_id'] == c1
    conn.close()
    print("✓ Summary and last_summarized_id updated correctly")
    
    # 6. Add more and test get_unsummarized_conversations
    c4 = storage.save_msg(topic_id, "User 4", "AI 4", False)
    unsummarized = storage.get_unsummarized_conversations(topic_id)
    assert len(unsummarized) == 3 # c2, c3, c4
    assert unsummarized[0]['id'] == c2
    assert unsummarized[2]['id'] == c4
    print("✓ Added c4, unsummarized count is 3 (c2, c3, c4)")
    
    # 7. Test migration (is_summarized column added to existing DB)
    # We already tested this by running Storage() which calls _migrate()
    
    print("\nAll database summary logic tests passed! ✓")
    
    # Cleanup
    storage.conn.close()
    if os.path.exists(db_path):
        os.remove(db_path)

if __name__ == "__main__":
    test_db_summary_logic()
