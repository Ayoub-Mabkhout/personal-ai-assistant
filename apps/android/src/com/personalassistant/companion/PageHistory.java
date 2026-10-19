package com.personalassistant.companion;

import java.util.ArrayDeque;

/** Back visits previous tabs; a direct entry falls back to Home. */
final class PageHistory {
    private final ArrayDeque<Integer> pages=new ArrayDeque<>();
    void visit(int previous,int next){
        if(previous==next)return;
        if(pages.size()==32)pages.removeFirst();
        pages.addLast(previous);
    }
    int back(int current){return pages.isEmpty()?(current==0?-1:0):pages.removeLast();}
    void clear(){pages.clear();}
    int[] save(){int[] saved=new int[pages.size()];int i=0;for(int page:pages)saved[i++]=page;return saved;}
    void restore(int[] saved){clear();if(saved!=null)for(int page:saved)if(page>=0&&page<5){if(pages.size()==32)pages.removeFirst();pages.addLast(page);}}
}
