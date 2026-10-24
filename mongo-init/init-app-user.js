// Runs ONCE, the first time MongoDB starts with an empty data directory.
// Creates a least-privilege user for the application: it may only
// read/write the "bookhub" database (not administer the server).
const dbName = process.env.APP_DB_NAME || "bookhub";
db.getSiblingDB(dbName).createUser({
  user: process.env.APP_DB_USER,
  pwd: process.env.APP_DB_PASSWORD,
  roles: [{ role: "readWrite", db: dbName }],
});
print("Created application user '" + process.env.APP_DB_USER + "' on database '" + dbName + "'");
