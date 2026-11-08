package demo;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

public class GreetingRepository {
    private final Connection conn;

    public GreetingRepository(Connection conn) {
        this.conn = conn;
    }

    public String greetingFor(long id) throws SQLException {
        try (PreparedStatement ps = conn.prepareStatement("SELECT text FROM greetings WHERE id = ?")) {
            ps.setLong(1, id);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next() ? rs.getString(1) : "Hello";
            }
        }
    }
}
