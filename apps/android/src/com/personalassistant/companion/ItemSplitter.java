package com.personalassistant.companion;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.regex.Pattern;

/** Splits quick-add text into items; the server enforces the same 100 item and 300 character limits. */
final class ItemSplitter {
    private static final String[] COMPOUNDS={"mac and cheese","salt and pepper","oil and vinegar"};
    private static final Pattern SEPARATOR=Pattern.compile("\\s*(?:,|;|\\band\\b|\\bund\\b)\\s*",Pattern.CASE_INSENSITIVE);
    private ItemSplitter(){}

    /** "milk, eggs and bread" becomes three items; a few common pairs stay together. */
    static List<String> split(String text){
        Map<String,String> keys=new LinkedHashMap<>();String value=text==null?"":text;
        for(String phrase:COMPOUNDS){Pattern p=Pattern.compile(Pattern.quote(phrase),Pattern.CASE_INSENSITIVE);if(p.matcher(value).find()){String key="COMPOUND"+keys.size();keys.put(key,phrase);value=p.matcher(value).replaceAll(key);}}
        List<String> names=new ArrayList<>();
        for(String part:SEPARATOR.split(value)){String name=part.trim();for(Map.Entry<String,String> e:keys.entrySet())name=name.replace(e.getKey(),e.getValue());if(!name.isEmpty()&&names.size()<100)names.add(name.length()>300?name.substring(0,300):name);}
        return names;
    }
}
