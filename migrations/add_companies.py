"""
Migration script to add companies collection and company_id to users
Run this script once to set up the company management feature
"""

from pymongo import MongoClient
from bson import ObjectId
from time import time
import os


# Get MongoDB connection string from environment or use default
MONGO_URI = os.getenv('MONGO_URI', 'mongodb+srv://wizzmod:wizzmod@wizzmod-cluster.gu90dde.mongodb.net/dps?retryWrites=true&w=majority')
DB_NAME = os.getenv('DB_NAME', 'serviceapp')

def run_migration():
    client = MongoClient(MONGO_URI)
    db = client[DB_NAME]
    
    print("Starting migration: Adding companies collection and company_id to users...")
    
    # Step 1: Create companies collection with indexes
    print("\n1. Setting up companies collection...")
    if 'companies' not in db.list_collection_names():
        db.create_collection('companies')
        print("   ✓ Created companies collection")
    
    # Create unique index on company email
    db.companies.create_index('email', unique=True)
    print("   ✓ Created unique index on company email")
    
    # Step 2: Create a default company for existing users
    print("\n2. Creating default company...")
    default_company = {
        'name': 'Default Organization',
        'email': 'admin@defaultorg.com',
        'phone': '',
        'created_at': int(time()),
        'updated_at': int(time()),
        'active': True
    }
    
    existing_default = db.companies.find_one({'email': 'admin@defaultorg.com'})
    if existing_default:
        default_company_id = existing_default['_id']
        print(f"   ✓ Default company already exists (ID: {default_company_id})")
    else:
        result = db.companies.insert_one(default_company)
        default_company_id = result.inserted_id
        print(f"   ✓ Created default company (ID: {default_company_id})")
    
    # Step 3: Add company_id to all existing users without one
    print("\n3. Updating existing users...")
    users_without_company = db.users.find({'company_id': {'$exists': False}})
    count = 0
    
    for user in users_without_company:
        db.users.update_one(
            {'_id': user['_id']},
            {'$set': {'company_id': default_company_id}}
        )
        count += 1
    
    print(f"   ✓ Updated {count} users with default company")
    
    # Step 4: Create index on users.company_id for performance
    print("\n4. Creating indexes...")
    db.users.create_index('company_id')
    print("   ✓ Created index on users.company_id")
    
    # Step 5: Verify migration
    print("\n5. Verifying migration...")
    total_companies = db.companies.count_documents({'active': True})
    total_users = db.users.count_documents({})
    users_with_company = db.users.count_documents({'company_id': {'$exists': True}})
    
    print(f"   ✓ Total companies: {total_companies}")
    print(f"   ✓ Total users: {total_users}")
    print(f"   ✓ Users with company: {users_with_company}")
    
    if users_with_company == total_users:
        print("\n✅ Migration completed successfully!")
    else:
        print(f"\n⚠️  Warning: {total_users - users_with_company} users still without company")
    
    client.close()

if __name__ == '__main__':
    try:
        run_migration()
    except Exception as e:
        print(f"\n❌ Migration failed: {str(e)}")
        raise
